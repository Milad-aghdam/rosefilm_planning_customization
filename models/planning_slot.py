from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

class PlanningSlot(models.Model):
    _inherit = 'planning.slot'

    workcenter_id = fields.Many2one('mrp.workcenter', string='مرکز کاری', index=True, store=True)
    department_id = fields.Many2one('hr.department',  string='دپارتمان', index=True, store=True)
    
    # The shift_type field is now ONLY for work centers.
    shift_type = fields.Selection([
        ('1', 'شیفت ۱'),
        ('2', 'شیفت ۲'),
        ('3', 'شیفت ۳'),
    ], string="شیفت")
    
    gantt_grouping_name = fields.Char(string="Gantt Label", compute='_compute_gantt_grouping_name', store=True)

    @api.depends('workcenter_id', 'department_id', 'shift_type')
    def _compute_gantt_grouping_name(self):
        for slot in self:
            name = slot.sudo().workcenter_id.name or slot.sudo().department_id.name or ''
            
            # VVVV --- THIS IS THE KEY LOGIC CHANGE --- VVVV
            # Only add the shift label IF a workcenter is selected.
            if slot.workcenter_id and slot.shift_type:
                shift_label = dict(self._fields['shift_type'].selection).get(slot.shift_type, '')
                slot.gantt_grouping_name = f"{name} - {shift_label}"
            else:
                # For departments, the label is just the department name.
                slot.gantt_grouping_name = name

    def _get_axis_resource(self):
        self.ensure_one()
        if self.workcenter_id:
            if not self.workcenter_id.planning_resource_id:
                self.workcenter_id.action_create_planning_resource()
            return self.workcenter_id.planning_resource_id
        if self.department_id:
            if not self.department_id.planning_resource_id:
                self.department_id.action_create_planning_resource()
            return self.department_id.planning_resource_id
        return False

    def _sync_resource_from_axis(self):
        for rec in self:
            rec.resource_id = rec._get_axis_resource() or False

    @api.onchange('workcenter_id')
    def _onchange_workcenter_id(self):
        if self.workcenter_id:
            self.department_id = False

    @api.onchange('department_id')
    def _onchange_department_id(self):
        if self.department_id:
            self.workcenter_id = False

    @api.model_create_multi
    def create(self, vals_list):
        slots = super().create(vals_list)
        slots._sync_resource_from_axis()
        return slots

    def write(self, vals):
        res = super().write(vals)
        if 'workcenter_id' in vals or 'department_id' in vals:
            self._sync_resource_from_axis()
        return res
        
    @api.constrains('start_datetime', 'end_datetime', 'workcenter_id', 'shift_type')
    def _check_duplicate_shift(self):
        _logger.info("--- Running _check_duplicate_shift constraint ---")
        # VVVV --- SIMPLIFIED CONSTRAINT --- VVVV
        # This check now ONLY runs for workcenters with a shift selected.
        for slot in self.filtered(lambda s: s.workcenter_id and s.shift_type):
            domain = [
                ('id', '!=', slot.id),
                ('shift_type', '=', slot.shift_type),
                ('workcenter_id', '=', slot.workcenter_id.id),
                ('start_datetime', '<', slot.end_datetime),
                ('end_datetime', '>', slot.start_datetime),
            ]
            if self.search_count(domain) > 0:
                shift_label = dict(self._fields['shift_type'].selection).get(slot.shift_type)
                name = slot.sudo().workcenter_id.name
                raise ValidationError(
                    _("A schedule for '%(name)s - %(shift)s' already exists for this time period. You cannot double book the same shift.",
                      name=name, shift=shift_label)
                )