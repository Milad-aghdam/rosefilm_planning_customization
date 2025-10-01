from odoo import models, fields, api, _

class MrpProductionCapacityWizard(models.TransientModel):
    _name = 'mrp.production.capacity.wizard'
    _description = 'Capacity Check Result Wizard'

    message = fields.Html(string="نتیجه", readonly=True, sanitize=True)
    proposed_date = fields.Date(string="تاریخ پیشنهادی", readonly=True)

    def action_apply_date(self):
        self.ensure_one()
        mo = self.env.context.get('active_id') and self.env['mrp.production'].browse(self.env.context['active_id'])
        if mo and self.proposed_date:
            mo.requested_date = self.proposed_date
        return {'type': 'ir.actions.act_window_close'}
