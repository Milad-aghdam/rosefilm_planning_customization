# models/mrp_production.py
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, date, time, timedelta
import pytz
from odoo.tools.misc import format_date

SHIFT_WINDOWS = {
    '1': (time(8, 0),  time(16, 0)),
    '2': (time(16, 0), time(0, 0)),   # to midnight (next day)
    '3': (time(0, 0),  time(8, 0)),
}

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    requested_workcenter_id = fields.Many2one('mrp.workcenter', string='Requested Work Center')
    requested_shift_type = fields.Selection([('1','Shift 1'),('2','Shift 2'),('3','Shift 3')], string='Requested Shift')
    requested_date = fields.Date(string='Requested Date')
    requested_duration_minutes = fields.Float(string='Requested Minutes', help="Remaining time to be planned for this work center.")
    
    capacity_check_result = fields.Char(string="Capacity Status", readonly=True)

    # ...
    # All helper methods (_get_user_tz, _compute_shift_bounds, etc.) remain the same
    # ...
    # ----- Helper methods for capacity checking -----

    def _get_user_tz(self):
        return pytz.timezone(self.env.user.tz or 'UTC')

    def _compute_shift_bounds(self, d, shift_type):
        if shift_type not in SHIFT_WINDOWS: raise ValidationError(_("Unknown shift type."))
        start_t, end_t = SHIFT_WINDOWS[shift_type]
        tz = self._get_user_tz()
        start_local = tz.localize(datetime.combine(d, start_t))
        end_day = d if (end_t > start_t) else (d + timedelta(days=1))
        end_local = tz.localize(datetime.combine(end_day, end_t))
        return start_local.astimezone(pytz.utc).replace(tzinfo=None), end_local.astimezone(pytz.utc).replace(tzinfo=None)

    def _shift_is_holiday(self, wc, start_dt, end_dt):
        cal = wc.resource_calendar_id
        if not cal: return False
        return self.env['resource.calendar.leaves'].search_count([('calendar_id', '=', cal.id), ('date_from', '<', end_dt), ('date_to', '>', start_dt)]) > 0

    def _get_busy_intervals(self, wc_id, shift_type, start_dt, end_dt):
        slots = self.env['planning.slot'].search([('workcenter_id', '=', wc_id), ('shift_type', '=', shift_type), ('start_datetime', '<', end_dt), ('end_datetime', '>', start_dt)])
        iv = sorted([(s.start_datetime, s.end_datetime) for s in slots])
        merged = []
        for start, end in iv:
            if not merged or start > merged[-1][1]: merged.append([start, end])
            else: merged[-1][1] = max(merged[-1][1], end)
        return [(a, b) for a, b in merged]

    def _has_free_block(self, start_dt, end_dt, busy, need_minutes: float):
        free = []
        cursor = start_dt
        for b1, b2 in busy:
            if b1 > cursor: free.append((cursor, b1))
            cursor = max(cursor, b2)
        if cursor < end_dt: free.append((cursor, end_dt))
        return any((b2 - b1).total_seconds() >= (need_minutes * 60) for b1, b2 in free)
        
    def _is_capacity_available(self, check_date):
        self.ensure_one()
        if not (self.requested_workcenter_id and self.requested_shift_type and check_date and self.requested_duration_minutes): return False, _("Missing information.")
        wc = self.requested_workcenter_id
        try:
            sh_start, sh_end = self._compute_shift_bounds(check_date, self.requested_shift_type)
            if self._shift_is_holiday(wc, sh_start, sh_end): return False, _("تعطیل رسمی")
            busy = self._get_busy_intervals(wc.id, self.requested_shift_type, sh_start, sh_end)
            if not self._has_free_block(sh_start, sh_end, busy, self.requested_duration_minutes): return False, _("ظرفیت کافی پیوسته در دسترس نیست.")
            return True, _("ظرفیت موجود است")
        except Exception as e: return False, str(e)


    def _validate_or_find_capacity(self):
        self.ensure_one()
        start_search_date = self.requested_date or date.today()
        
        SEARCH_LIMIT_DAYS = 90
        for i in range(SEARCH_LIMIT_DAYS):
            check_date = start_search_date + timedelta(days=i)
            is_available, reason = self._is_capacity_available(check_date)
            
            if is_available:
                self.requested_date = check_date # Update the date on the main form
                
                # Use format_date to show the date in the user's local calendar (e.g., Jalali)
                formatted_date = format_date(self.env, check_date)

                if check_date == start_search_date:
                    # Use <br/> for line breaks to ensure correct formatting
                    return _("ظرفیت در تاریخ درخواستی شما موجود است:<br/><br/><b>%s</b>") % formatted_date
                else:
                    return _("تاریخ درخواستی شما تکمیل بود.<br/>اولین زمان خالی پیدا و در تاریخ زیر تنظیم شد:<br/><br/><b>%s</b>") % formatted_date

        raise UserError(_("متاسفانه ظرفیتی برای شیفت انتخابی در %s روز آینده پیدا نشد.") % SEARCH_LIMIT_DAYS)

    def action_check_planning_capacity(self):
        self.ensure_one()
        message = self._validate_or_find_capacity()
        wizard = self.env['mrp.production.capacity.wizard'].create({'message': message})
        return {
            'name': _('نتیجه بررسی ظرفیت'),
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production.capacity.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }
    
    # --- NEW: Action for the refresh button to calculate remaining duration ---
    def action_recalculate_remaining_duration(self):
        self.ensure_one()
        self._compute_remaining_duration()
        return { 'type': 'ir.actions.act_window_close' }

    # ... button_plan and action_plan remain the same ...
    def button_plan(self):
        if not self.requested_date:
             raise UserError(_("Please select a date or use the 'Check Capacity' button to find the first available slot before planning."))
        is_available, reason = self._is_capacity_available(self.requested_date)
        if not is_available:
            raise UserError(_("Cannot plan. No capacity available on %s: %s") % (self.requested_date.strftime('%Y-%m-%d'), reason))
        return super().button_plan()

    def action_plan(self):
        if not self.requested_date:
             raise UserError(_("Please select a date or use the 'Check Capacity' button to find the first available slot before planning."))
        is_available, reason = self._is_capacity_available(self.requested_date)
        if not is_available:
            raise UserError(_("Cannot plan. No capacity available on %s: %s") % (self.requested_date.strftime('%Y-%m-%d'), reason))
        return super().action_plan()


    @api.onchange('requested_workcenter_id', 'workorder_ids')
    def _onchange_prefill_planning_request(self):
        """
        This single method handles all automatic field updates for the planning request.
        It calculates remaining duration and suggests a start date.
        """
        if self.requested_workcenter_id and self.workorder_ids:
            relevant_wos = self.workorder_ids.filtered(lambda w: w.workcenter_id == self.requested_workcenter_id)
            total_duration_minutes = sum(relevant_wos.mapped('duration_expected'))

            existing_slots = self.env['planning.slot'].search([
                ('workorder_id', 'in', relevant_wos.ids)
            ])
            planned_duration_minutes = sum(slot.allocated_hours * 60 for slot in existing_slots)

            self.requested_duration_minutes = max(0, total_duration_minutes - planned_duration_minutes)

            if not self.requested_date:
                last_slot = self.env['planning.slot'].search(
                    [('workorder_id', 'in', self.workorder_ids.ids)],
                    order='end_datetime desc', limit=1
                )
                if last_slot:
                    self.requested_date = last_slot.end_datetime.date()
                else:
                    self.requested_date = self.date_start.date() if self.date_start else date.today()
        else:
            self.requested_duration_minutes = 0.0