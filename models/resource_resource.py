from odoo import models, fields

class ResourceResource(models.Model):
    _inherit = 'resource.resource'

    is_workcenter  = fields.Boolean(string='Is Workcenter')
    is_department  = fields.Boolean(string='Is Department')
    workcenter_id  = fields.Many2one('mrp.workcenter', ondelete='set null', index=True)
    department_id  = fields.Many2one('hr.department',  ondelete='set null', index=True)

    def name_get(self):
        res = []
        for r in self:
            lbl = r.name
            if r.workcenter_id:
                lbl = f"[WC] {r.workcenter_id.sudo().display_name}"
            elif r.department_id:
                lbl = f"[Dept] {r.department_id.sudo().display_name}"
            res.append((r.id, lbl))
        return res
