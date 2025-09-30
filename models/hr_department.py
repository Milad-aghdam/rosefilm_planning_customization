# your_module/models/hr_department.py
from odoo import models, fields

class HrDepartment(models.Model):
    _inherit = 'hr.department'

    planning_resource_id = fields.Many2one('resource.resource', domain=[('is_department','=',True)], ondelete='set null',string='Planning Resource',)

    shift_one_head_id   = fields.Many2one('res.users', string='Shift 1 Supervisor')
    shift_two_head_id   = fields.Many2one('res.users', string='Shift 2 Supervisor')
    shift_three_head_id = fields.Many2one('res.users', string='Shift 3 Supervisor')

    def action_create_planning_resource(self):
        for dep in self:
            if not dep.planning_resource_id:
                dep.planning_resource_id = self.env['resource.resource'].create({
                    'name': dep.name,
                    'company_id': dep.company_id.id or False,
                    'is_department': True,
                    'department_id': dep.id,
                })
