# models/mrp_production.py
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, date, time, timedelta
import pytz
import math
from odoo.tools.misc import format_date

# بازه‌های شیفت (به ساعت محلی کاربر)
SHIFT_WINDOWS = {
    '1': (time(8, 0),  time(16, 0)),
    '2': (time(16, 0), time(0, 0)),   # تا نیمه‌شبِ روز بعد
    '3': (time(0, 0),  time(8, 0)),
}


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    # ورودی‌های درخواست برنامه‌ریزی
    requested_workcenter_id = fields.Many2one('mrp.workcenter', string='Requested Work Center')
    requested_shift_type = fields.Selection(
        [('1', 'Shift 1'), ('2', 'Shift 2'), ('3', 'Shift 3')],
        string='Requested Shift'
    )
    requested_date = fields.Date(string='Requested Date')

    # دقایق درخواستی: مقدار محاسباتی (WO expected − planned slots) با fallback از BoM
    requested_duration_minutes = fields.Float(
        string='Requested Minutes',
        digits=(16, 0),                 # دقیقه، بدون اعشار
        compute='_compute_remaining_duration',
        readonly=True,
        store=False,
        help="Remaining minutes for this workcenter: sum of WO expected minus planned slots. "
             "If WOs have no duration yet, estimate from BoM operations of the same workcenter."
    )

    # وضعیت/پیام (اختیاری)
    capacity_check_result = fields.Char(string="Capacity Status", readonly=True)

    # هم‌تراز با فیلدهای بومی اودو در بالای فرم
    requested_start_datetime = fields.Datetime(related='date_start',    readonly=False, store=True)
    requested_end_datetime   = fields.Datetime(related='date_finished', readonly=False, store=True)

    # ─────────────────────────────────────────────────────────────
    # onchange های سبک
    # ─────────────────────────────────────────────────────────────
    @api.onchange('requested_start_datetime')
    def _onchange_set_requested_date_from_start(self):
        for rec in self:
            if rec.requested_start_datetime:
                rec.requested_date = fields.Date.to_date(rec.requested_start_datetime)

    @api.onchange('requested_workcenter_id', 'workorder_ids')
    def _onchange_prefill_planning_request(self):
        """اگر تاریخ خالی است، از آخرین اسلات یا تاریخ شروع سفارش پر کن."""
        for rec in self:
            if rec.requested_workcenter_id and rec.workorder_ids and not rec.requested_date:
                last_slot = rec.env['planning.slot'].search(
                    [('workorder_id', 'in', rec.workorder_ids.ids)],
                    order='end_datetime desc', limit=1
                )
                if last_slot:
                    rec.requested_date = last_slot.end_datetime.date()
                else:
                    rec.requested_date = (rec.date_start.date()
                                          if rec.date_start else fields.Date.context_today(rec))

    # ─────────────────────────────────────────────────────────────
    # Helpers: TZ و بازهٔ شیفت و اشغال/آزاد
    # ─────────────────────────────────────────────────────────────
    def _get_user_tz(self):
        return pytz.timezone(self.env.user.tz or 'UTC')

    def _compute_shift_bounds(self, d, shift_type):
        """
        ورودی: تاریخ (date) و شیفت.
        خروجی: شروع/پایان شیفت به UTC naive (datetime) برای مقایسه با DB.
        """
        if shift_type not in SHIFT_WINDOWS:
            raise ValidationError(_("Unknown shift type."))
        start_t, end_t = SHIFT_WINDOWS[shift_type]
        tz = self._get_user_tz()
        start_local = tz.localize(datetime.combine(d, start_t))
        end_day = d if (end_t > start_t) else (d + timedelta(days=1))
        end_local = tz.localize(datetime.combine(end_day, end_t))
        return (
            start_local.astimezone(pytz.utc).replace(tzinfo=None),
            end_local.astimezone(pytz.utc).replace(tzinfo=None),
        )

    def _shift_is_holiday(self, wc, start_dt, end_dt):
        """بررسی مرخصی/تعطیلی روی تقویم مرکزکار."""
        cal = wc.resource_calendar_id
        if not cal:
            return False
        return self.env['resource.calendar.leaves'].search_count([
            ('calendar_id', '=', cal.id),
            ('date_from', '<', end_dt),
            ('date_to', '>', start_dt),
        ]) > 0

    def _get_busy_intervals(self, wc_id, shift_type, start_dt, end_dt):
        """بازه‌های اشغال‌شده در planning.slot برای همان مرکزکار/شیفت."""
        slots = self.env['planning.slot'].search([
            ('workcenter_id', '=', wc_id),
            ('shift_type', '=', shift_type),
            ('start_datetime', '<', end_dt),
            ('end_datetime', '>', start_dt),
        ])
        intervals = sorted((s.start_datetime, s.end_datetime) for s in slots)
        # Merge intervals
        merged = []
        for s, e in intervals:
            if not merged or s > merged[-1][1]:
                merged.append([s, e])
            else:
                merged[-1][1] = max(merged[-1][1], e)
        return [(a, b) for a, b in merged]

    def _has_free_block(self, start_dt, end_dt, busy, need_minutes: float):
        """بررسی وجود بازهٔ آزاد پیوسته با طول موردنیاز داخل بازهٔ شیفت."""
        free = []
        cursor = start_dt
        for b1, b2 in busy:
            if b1 > cursor:
                free.append((cursor, b1))
            cursor = max(cursor, b2)
        if cursor < end_dt:
            free.append((cursor, end_dt))
        need_seconds = (need_minutes or 0.0) * 60.0
        return any((b2 - b1).total_seconds() >= need_seconds for b1, b2 in free)

    def _is_capacity_available(self, check_date):
        """
        فقط بررسی می‌کند آیا یک بازهٔ پیوسته به طول requested_duration_minutes
        داخل شیفت انتخابی در روز check_date پیدا می‌شود یا نه.
        طول شیفت را دست نمی‌زنیم. اگر مقدار درخواست صفر/منفی بود، به‌طور واضح خطا می‌دهیم.
        """
        self.ensure_one()
        if not (self.requested_workcenter_id and self.requested_shift_type and check_date):
            return False, _("اطلاعات ناقص: مرکز کار/شیفت/تاریخ")

        need_min = int(self.requested_duration_minutes or 0)
        if need_min <= 0:
            return False, _("مقدار «دقایق درخواستی» باید بزرگ‌تر از صفر باشد.")

        wc = self.requested_workcenter_id
        try:
            sh_start, sh_end = self._compute_shift_bounds(check_date, self.requested_shift_type)

            # تعطیلی؟
            if self._shift_is_holiday(wc, sh_start, sh_end):
                return False, _("این روز/شیفت طبق تقویم مرکز کار تعطیل است.")

            # بازه‌های اشغال‌شده
            busy = self._get_busy_intervals(wc.id, self.requested_shift_type, sh_start, sh_end)

            # اگر اصلاً اسلاتی نیست → کل شیفت آزاد است
            if not busy:
                return True, _("بدون تداخل")

            # محاسبهٔ آزادها + بیشترین بازهٔ آزاد برای پیام شفاف
            free = []
            cursor = sh_start
            for b1, b2 in busy:
                if b1 > cursor:
                    free.append((cursor, b1))
                cursor = max(cursor, b2)
            if cursor < sh_end:
                free.append((cursor, sh_end))

            max_free_min = 0
            for f1, f2 in free:
                span_min = int((f2 - f1).total_seconds() // 60)
                max_free_min = max(max_free_min, span_min)
                if span_min >= need_min:
                    return True, _("در بازهٔ آزاد: %s تا %s") % (f1.strftime('%H:%M'), f2.strftime('%H:%M'))

            # اگر به اینجا رسیدیم یعنی بازهٔ آزاد به طول خواسته‌شده پیدا نشد
            return False, _("بیشترین بازهٔ آزاد این شیفت: %s دقیقه") % max_free_min

        except Exception as e:
            # هر خطای پیش‌بینی‌نشده را به‌صورت دلیل برگردان تا معلوم شود چه خبر است
            return False, _("خطا: %s") % str(e)



    def _validate_or_find_capacity(self):
        self.ensure_one()
        start_search_date = self.requested_date or fields.Date.context_today(self)
        SEARCH_LIMIT_DAYS = 90

        for i in range(SEARCH_LIMIT_DAYS):
            check_date = start_search_date + timedelta(days=i)
            ok, reason = self._is_capacity_available(check_date)
            if ok:
                d = format_date(self.env, check_date)  # جلالی/لوکال
                h = self._get_shift_display_times(check_date, self.requested_shift_type)
                if i == 0:
                    return (
                        "<div dir='rtl' style='text-align:right'>"
                        "<h4>✅ ظرفیت موجود است</h4>"
                        "<ul style='margin:0; padding-right:18px'>"
                        f"<li><b>تاریخ:</b> {d}</li>"
                        f"<li><b>ساعت شیفت:</b> {h}</li>"
                        "</ul>"
                        "<div style='color:#666;margin-top:4px'>بدون تداخل</div>"
                        "</div>"
                    )
                else:
                    return (
                        "<div dir='rtl' style='text-align:right'>"
                        "<h4>ℹ️ تاریخ درخواستی تکمیل بود</h4>"
                        "<ul style='margin:0; padding-right:18px'>"
                        f"<li><b>اولین زمان خالی:</b> {d}</li>"
                        f"<li><b>ساعت شیفت:</b> {h}</li>"
                        "</ul>"
                        f"<div style='color:#666;margin-top:4px'>{reason or ''}</div>"
                        "</div>"
                    )


        # هیچ روزی نشد → دلیل روز اول را هم کنار پیام بدهیم برای فهم بهتر
        first_ok, first_reason = self._is_capacity_available(start_search_date)
        raise UserError(
            _("متاسفانه ظرفیتی برای شیفت انتخابی در %(days)s روز آینده پیدا نشد.") % {'days': SEARCH_LIMIT_DAYS}
            + (f"\n({first_reason})" if first_reason else "")
        )





    # ─────────────────────────────────────────────────────────────
    # اکشن‌ها (دکمه‌ها)
    # ─────────────────────────────────────────────────────────────
    def _ensure_request_inputs(self):
        """ولیدیشن ورودی‌ها (جای modifiers UI)."""
        self.ensure_one()
        missing = []
        if not self.requested_workcenter_id:
            missing.append(_("مرکز کاری"))
        if not self.requested_shift_type:
            missing.append(_("شیفت"))
        # یا دقیقهٔ مثبت داشته باشیم یا بازهٔ زمان بالا (برای برنامه‌ریزی‌های خاص)
        if not self.requested_duration_minutes and not (self.requested_start_datetime and self.requested_end_datetime):
            missing.append(_("بازه یا مدت زمان"))
        if missing:
            raise UserError(_("اطلاعات ناقص است: %s") % ", ".join(missing))

    def action_check_planning_capacity(self):
        self.ensure_one()
        self._ensure_request_inputs()
        message = self._validate_or_find_capacity()
        wiz = self.env['mrp.production.capacity.wizard'].create({
            'message': message,
            'proposed_date': check_date, 
        })
        return {
            'name': _('نتیجه بررسی ظرفیت'),
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production.capacity.wizard',
            'view_mode': 'form',
            'res_id': wiz.id,
            'target': 'new',
        }


    def button_plan(self):
        """پیش از برنامه‌ریزی، تاریخِ درخواستی را اعتبارسنجی کن."""
        if not self.requested_date:
            raise UserError(_("Please select a date or use the 'Check Capacity' button to find the first available slot before planning."))
        is_available, reason = self._is_capacity_available(self.requested_date)
        if not is_available:
            raise UserError(_("Cannot plan. No capacity available on %s: %s") % (self.requested_date.strftime('%Y-%m-%d'), reason))
        return super().button_plan()

    def action_plan(self):
        """پیش از برنامه‌ریزی انبوه، ظرفیت همان روز را چک کن."""
        if not self.requested_date:
            raise UserError(_("Please select a date or use the 'Check Capacity' button to find the first available slot before planning."))
        is_available, reason = self._is_capacity_available(self.requested_date)
        if not is_available:
            raise UserError(_("Cannot plan. No capacity available on %s: %s") % (self.requested_date.strftime('%Y-%m-%d'), reason))
        return super().action_plan()

    @api.depends(
    'requested_workcenter_id',
    'workorder_ids.duration_expected',
    'bom_id.operation_ids',
    'bom_id.operation_ids.time_cycle',
    'bom_id.operation_ids.time_cycle_manual',
    'product_qty',
    )
    def _compute_remaining_duration(self):
        import math
        for mo in self:
            minutes = 0.0
            wc = mo.requested_workcenter_id
            qty = float(mo.product_qty or 0.0)

            def _sum_planned_min(wos):
                slots = mo.env['planning.slot'].sudo().search([('workorder_id', 'in', wos.ids)])
                return sum((s.allocated_hours or 0.0) * 60.0 for s in slots)

            def _estimate_from_ops(ops):
                est = 0.0
                for op in ops:
                    per_cycle_min = float(getattr(op, 'time_cycle_manual', 0.0) or getattr(op, 'time_cycle', 0.0) or 0.0)
                    # پشتیبانی امن از فیلدهای نسخه‌های مختلف
                    batch_enabled = bool(getattr(op, 'batch', False))
                    batch_size    = float(getattr(op, 'batch_size', 0.0)) if batch_enabled else 0.0
                    qty_by_cycle  = float(getattr(op, 'qty_by_cycle', 0.0))
                    if qty <= 0 or per_cycle_min <= 0:
                        continue
                    if batch_enabled and batch_size > 0:
                        cycles = math.ceil(qty / batch_size)
                    elif qty_by_cycle > 0:
                        cycles = math.ceil(qty / qty_by_cycle)
                    else:
                        cycles = math.ceil(qty)
                    est += per_cycle_min * cycles
                return est

            # 1) WOهای همین WC با duration
            if wc:
                wos_wc = mo.workorder_ids.filtered(lambda w: w.workcenter_id == wc)
                total_wo_min_wc = sum(wos_wc.mapped('duration_expected'))
                if total_wo_min_wc > 0:
                    minutes = max(0.0, float(total_wo_min_wc) - _sum_planned_min(wos_wc))
                else:
                    # 2) اگر برای این WC صفر شد، از کل WOهای MO استفاده کن (برای اینکه صفر نبینی)
                    total_wo_min_all = sum(mo.workorder_ids.mapped('duration_expected'))
                    if total_wo_min_all > 0:
                        minutes = max(0.0, float(total_wo_min_all) - _sum_planned_min(mo.workorder_ids))
                    else:
                        # 3) BoM فقط همین WC
                        if mo.bom_id:
                            ops_wc = mo.bom_id.operation_ids.filtered(lambda o: o.workcenter_id == wc)
                            est_wc = _estimate_from_ops(ops_wc)
                            if est_wc > 0:
                                minutes = est_wc
                            else:
                                # 4) BoM همهٔ عملیات (به‌عنوان آخرین شانس)
                                minutes = _estimate_from_ops(mo.bom_id.operation_ids)
            else:
                # WC انتخاب نشده → از کل WOها یا BoM کل تخمین بزن
                total_wo_min_all = sum(mo.workorder_ids.mapped('duration_expected'))
                if total_wo_min_all > 0:
                    minutes = max(0.0, float(total_wo_min_all) - _sum_planned_min(mo.workorder_ids))
                elif mo.bom_id:
                    minutes = _estimate_from_ops(mo.bom_id.operation_ids)

            # پیشنهاد تاریخ اگر خالی است
            if not mo.requested_date:
                last_slot = mo.env['planning.slot'].sudo().search(
                    [('workorder_id', 'in', mo.workorder_ids.ids)],
                    order='end_datetime desc', limit=1
                )
                if last_slot:
                    mo.requested_date = last_slot.end_datetime.date()
                elif mo.date_start:
                    mo.requested_date = mo.date_start.date()
                else:
                    mo.requested_date = fields.Date.context_today(mo)

            mo.requested_duration_minutes = round(minutes or 0.0)
    
    def _get_shift_display_times(self, day: date, shift_type: str):
        if not shift_type or shift_type not in SHIFT_WINDOWS:
            return ""
        start_t, end_t = SHIFT_WINDOWS[shift_type]
        tz = self._get_user_tz()
        start_local = tz.localize(datetime.combine(day, start_t))
        end_day = day if (end_t > start_t) else (day + timedelta(days=1))
        end_local = tz.localize(datetime.combine(end_day, end_t))
        s = start_local.strftime('%H:%M')
        e = end_local.strftime('%H:%M')
        suffix = '' if end_day == day else ' (+1)'
        return f"{s} – {e}{suffix}"


    @api.onchange('requested_shift_type')
    def _onchange_reset_check_anchor(self):
        for rec in self:
            # همیشه از امروز شروع کن؛ ساده و قابل پیش‌بینی
            rec.requested_date = fields.Date.context_today(rec)
