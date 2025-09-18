from odoo import api, SUPERUSER_ID

def post_init_activate_departments(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Dept = env['hr.department'].with_context(active_test=False)
    # If there are zero active departments, unarchive all (idempotent & safe)
    if not env['hr.department'].search_count([('active', '=', True)]):
        Dept.search([('active', '=', False)]).write({'active': True})
