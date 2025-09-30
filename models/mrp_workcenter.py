# your_module/models/mrp_workcenter.py
from odoo import models, fields

class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'
    department_id     = fields.Many2one('hr.department', string='Department')
    planning_resource_id = fields.Many2one(
        'resource.resource', domain=[('is_workcenter','=',True)], ondelete='set null',
        string='Planning Resource',
    )
    primary_nominal_capacity_uom_id = fields.Many2one(
        'uom.uom', 
        string='ظرفیت اسمی اصلی', 
        help="واحد سنجش اصلی برای ظرفیت اسمی این مرکز کاری (مثال: کیلوگرم در ساعت)."
    )

    secondary_nominal_capacity_uom_id = fields.Many2one(
        'uom.uom', 
        string='ظرفیت اسمی فرعی', 
        help="واحد سنجش فرعی برای ظرفیت اسمی این مرکز کاری (مثال: متر در ساعت)."
    )
    
    primary_capacity_value = fields.Float(
        string="مقدار اصلی", 
        default=1.0)

    secondary_capacity_value = fields.Float(
        string="مقدار فرعی", 
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
