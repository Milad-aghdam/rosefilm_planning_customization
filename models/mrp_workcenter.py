# your_module/models/mrp_workcenter.py
from odoo import models, fields

class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'
    department_id     = fields.Many2one('hr.department', string='Department')
    planning_resource_id = fields.Many2one(
        'resource.resource', domain=[('is_workcenter','=',True)], ondelete='set null',
        string='Planning Resource',
    )
    nominal_capacity_uom_id = fields.Many2one(
        'uom.uom', 
        string='ظرفیت اسمی',
        help="واحد سنجش ظرفیت اسمی این مرکز کاری (مثال: کیلوگرم در ساعت، تعداد در روز)."
    )

    def action_create_planning_resource(self):
        for wc in self:
            if not wc.planning_resource_id:
                wc.planning_resource_id = self.env['resource.resource'].create({
                    'name': wc.name,
                    'company_id': wc.company_id.id or False,
                    'is_workcenter': True,
                    'workcenter_id': wc.id,
                    'calendar_id': wc.resource_calendar_id.id,
                })
            else:
                if wc.planning_resource_id.calendar_id != wc.resource_calendar_id:
                    wc.planning_resource_id.calendar_id = wc.resource_calendar_id.id
