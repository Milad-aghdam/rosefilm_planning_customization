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
        # This method is correct, no change needed
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
        # This method is correct, no change needed
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
        _logger.info(f"--- Entering CREATE with vals: {vals_list} ---")
        
        for vals in vals_list:
            resource = False
            if vals.get('workcenter_id'):
                workcenter = self.env['mrp.workcenter'].browse(vals['workcenter_id'])
                if not workcenter.planning_resource_id:
                    workcenter.action_create_planning_resource()
                resource = workcenter.planning_resource_id
            elif vals.get('department_id'):
                department = self.env['hr.department'].browse(vals['department_id'])
                if not department.planning_resource_id:
                    department.action_create_planning_resource()
                resource = department.planning_resource_id
            
            if resource:
                vals['resource_id'] = resource.id
                _logger.info(f"Setting resource_id to {resource.id} ({resource.name}) before create.")

        slots = super().create(vals_list)
        _logger.info(f"Slots created with IDs: {slots.ids}. Now recomputing fields.")
        # The compute method will run automatically because its dependencies changed.
        return slots

    def write(self, vals):
        res = super().write(vals)
        if 'workcenter_id' in vals or 'department_id' in vals:
            self._sync_resource_from_axis()
        return res
        
    def name_get(self):
        # This method is now obsolete because the Gantt view groups by gantt_grouping_name
        # but we can keep it for other views.
        return super().name_get()

    @api.depends('workcenter_id.name', 'department_id.name', 'shift_type', 'resource_id.name')
    def _compute_gantt_grouping_name(self):
        _logger.info("--- Running _compute_gantt_grouping_name ---")
        for slot in self:
            name = slot.sudo().workcenter_id.name or slot.sudo().department_id.name or ''
            
            # Fallback if name is still empty (e.g., during creation)
            if not name and slot.resource_id:
                name = slot.resource_id.sudo().name_get()[0][1]
                # Clean up the name if it has [WC] or [Dept] prefixes from resource.resource name_get
                if '[WC] ' in name: name = name.replace('[WC] ', '')
                if '[Dept] ' in name: name = name.replace('[Dept] ', '')

            shift_label = dict(self._fields['shift_type'].selection).get(slot.shift_type, '')
            _logger.info(f"Slot ID: {slot.id or 'New'}, WC/Dept: '{name}', Shift: '{shift_label}'")
            
            if shift_label:
                slot.gantt_grouping_name = f"{name} - {shift_label}"
            else:
                slot.gantt_grouping_name = name
            
            _logger.info(f"--> Computed gantt_grouping_name: '{slot.gantt_grouping_name}'")