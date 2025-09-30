from odoo import models, fields

class MrpProductionCapacityWizard(models.TransientModel):
    _name = 'mrp.production.capacity.wizard'
    _description = 'Capacity Check Result Wizard'

    message = fields.Text(string="نتیجه", readonly=True)