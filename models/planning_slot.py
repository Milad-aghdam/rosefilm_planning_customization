from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)

class PlanningSlot(models.Model):
    _inherit = 'planning.slot'

    workcenter_id = fields.Many2one('mrp.workcenter', string='مرکز کاری', index=True, store=True)
    department_id = fields.Many2one('hr.department',  string='دپارتمان', index=True, store=True)
    shift_type = fields.Selection([
        ('1', 'شیفت ۱'),
        ('2', 'شیفت ۲'),
        ('3', 'شیفت ۳'),
    ], string="شیفت")
    gantt_grouping_name = fields.Char(string="Gantt Label", compute='_compute_gantt_grouping_name', store=True)
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
        
    def name_get(self):
        result = []
        for slot in self:
            name = slot.workcenter_id.name or slot.department_id.name or slot.resource_id.name or ''
            if slot.shift_type:
                shift_label = dict(self._fields['shift_type'].selection).get(slot.shift_type)
                name = f"{name} - {shift_label}"
            result.append((slot.id, name))
        return result

    @api.depends('workcenter_id.name', 'department_id.name', 'shift_type')
    def _compute_gantt_grouping_name(self):
        _logger.info("--- Running _compute_gantt_grouping_name ---")
        for slot in self:
            name = slot.workcenter_id.name or slot.department_id.name or ''
            shift_label = dict(self._fields['shift_type'].selection).get(slot.shift_type, '')
            _logger.info(f"Slot ID: {slot.id}, WC: '{name}', Shift: '{shift_label}'")
            if shift_label:
                slot.gantt_grouping_name = f"{name} - {shift_label}"
            else:
                slot.gantt_grouping_name = name
            _logger.info(f"--> Computed gantt_grouping_name: '{slot.gantt_grouping_name}'")