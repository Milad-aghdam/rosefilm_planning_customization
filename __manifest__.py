{
    'name': 'Planning Customization',
    'version': '1.0',
    'summary': 'Adds custom fields and logic to the Planning module.',
    'author': 'Milad',
    'category': 'Human Resources/Planning',
    'depends': ['planning', 'project_forecast', 'project_timesheet_forecast_sale', 'hr', 'mrp'],
    'data': [
        'security/ir.model.access.csv',
        'wizards/capacity_wizard_views.xml',
        'views/planning_gantt_views.xml',
        'views/mrp_workcenter_views.xml',
        'views/mrp_production_views.xml',
    ],
    'sequence': 10,
    'installable': True,
    'application': False, 
    'auto_install': False,

}