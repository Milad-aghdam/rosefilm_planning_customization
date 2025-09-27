# models/mrp_production.py
from odoo import models, fields, api,_
from odoo.exceptions import ValidationError
from datetime import datetime, date, time, timedelta
import pytz

# Keep global shift windows super simple for Step 1
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
    requested_duration_minutes = fields.Float(string='Requested Minutes')

    # ----- Planning check (reads existing planning.slot records) -----
    def _get_user_tz(self):
        return pytz.timezone(self.env.user.tz or 'UTC')

    def _compute_shift_bounds(self, d, shift_type):
        if shift_type not in SHIFT_WINDOWS:
            raise ValidationError(_("Unknown shift type."))
        start_t, end_t = SHIFT_WINDOWS[shift_type]
        tz = self._get_user_tz()
        start_local = tz.localize(datetime.combine(d, start_t))
        end_day = d if (end_t > start_t) else (d + timedelta(days=1))
        end_local = tz.localize(datetime.combine(end_day, end_t))
        # Make them NAIVE UTC to match Odoo's Datetime fields
        start_utc = start_local.astimezone(pytz.utc).replace(tzinfo=None)
        end_utc   = end_local.astimezone(pytz.utc).replace(tzinfo=None)
        return start_utc, end_utc


    def _shift_is_holiday(self, wc, start_dt, end_dt):
        cal = wc.resource_calendar_id
        if not cal:
            return False
        leaves = self.env['resource.calendar.leaves'].search([
            ('calendar_id', '=', cal.id),
            ('date_from', '<=', start_dt),
            ('date_to', '>=', end_dt),
        ], limit=1)
        return bool(leaves)

    def _get_busy_intervals(self, wc_id, shift_type, start_dt, end_dt):
        slots = self.env['planning.slot'].search([
            ('workcenter_id', '=', wc_id),
            ('shift_type', '=', shift_type),
            ('start_datetime', '<', end_dt),
            ('end_datetime', '>', start_dt),
        ])
        iv = []
        for s in slots:
            s1, s2 = max(s.start_datetime, start_dt), min(s.end_datetime, end_dt)
            if s1 < s2:
                iv.append((s1, s2))
        iv.sort(key=lambda t: t[0])
        merged = []
        for cur in iv:
            if not merged or cur[0] > merged[-1][1]:
                merged.append(list(cur))
            else:
                merged[-1][1] = max(merged[-1][1], cur[1])
        return [(a, b) for a, b in merged]

    def _has_free_block(self, start_dt, end_dt, busy, need_minutes: float):
        # Free = window minus busy
        free = []
        cursor = start_dt
        for b1, b2 in busy:
            if b1 > cursor:
                free.append((cursor, b1))
            cursor = max(cursor, b2)
        if cursor < end_dt:
            free.append((cursor, end_dt))
        req = int(need_minutes * 60)
        return any((b2 - b1).total_seconds() >= req for b1, b2 in free)

    def _check_planning_capacity(self):
        for mo in self:
            if not (mo.requested_workcenter_id and mo.requested_shift_type and mo.requested_date and mo.requested_duration_minutes):
                continue
            wc = mo.requested_workcenter_id
            sh_start, sh_end = self._compute_shift_bounds(mo.requested_date, mo.requested_shift_type)

            # Holiday block (reads WC calendar; you already push this calendar to the planning resource). :contentReference[oaicite:1]{index=1}
            if self._shift_is_holiday(wc, sh_start, sh_end):
                raise ValidationError(_("Selected shift is a holiday for %s.") % wc.display_name)

            # Read Planning slots for this WC + Shift (these fields already exist in your module). :contentReference[oaicite:2]{index=2}
            busy = self._get_busy_intervals(wc.id, mo.requested_shift_type, sh_start, sh_end)
            if not self._has_free_block(sh_start, sh_end, busy, mo.requested_duration_minutes):
                raise ValidationError(_("No continuous %s minutes available on %s — Shift %s, %s.")
                                      % (int(mo.requested_duration_minutes), wc.display_name, mo.requested_shift_type, mo.requested_date))
        return True

    # Button users can click (and we also call it before planning)
    def action_check_planning_capacity(self):
        self._check_planning_capacity()
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _("Capacity OK"),
                           'message': _("Requested time fits in the selected shift."),
                           'sticky': False, 'type': 'success'}}

    # Hook into plan actions (covers both method names used across versions)
    def button_plan(self):
        self._check_planning_capacity()
        return super().button_plan()

    def action_plan(self):
        self._check_planning_capacity()
        return super().action_plan()

    @api.onchange('requested_workcenter_id')
    def _onchange_requested_workcenter_id(self):
        for mo in self:
            if mo.requested_workcenter_id and mo.workorder_ids:
                wos = mo.workorder_ids.filtered(lambda w: w.workcenter_id == mo.requested_workcenter_id)
                if wos:
                    mo.requested_duration_minutes = sum(wos.mapped('duration_expected')) or 0.0

