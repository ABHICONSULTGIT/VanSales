# Part of the Van Sales project.
{
    'name': "Van Sales - Base",
    'summary': "Sales vans, optional routes and daily visit plans",
    'description': """
Van Sales - Base
================

Foundation of the Van Sales suite. A salesman and his van are the base;
everything else is optional.

* **Sales vans** - a ``fleet.vehicle`` with a salesman and a stock location.
  The location is created automatically when the van is saved.
* **Routes** - an optional, reusable list of stops: customers, stop locations,
  or a customer at a stop location. A guideline, never a restriction.
* **Visit plans** - one salesman's day. A route can be given to it as a
  checklist; every sale he makes that day lands on it regardless.
* **Security** - three roles (User / Supervisor / Administrator), with record
  rules scoping a salesman to his own van, plans and visits.
""",
    'author': "BizTech Computers",
    'website': "https://biztechbh.biz/",
    'category': 'Inventory/Van Sales',
    'version': '19.0.2.0.0',
    'license': 'OPL-1',
    'depends': [
        'base',
        'mail',
        'stock',
        'fleet',
    ],
    'data': [
        'security/van_sales_groups.xml',
        'security/ir.model.access.csv',
        'security/van_sales_security.xml',
        'data/van_sales_data.xml',
        'wizard/van_sales_van_location_wizard_views.xml',
        'views/van_sales_stop_location_views.xml',
        'views/van_sales_route_views.xml',
        'views/van_sales_visit_views.xml',
        'views/van_sales_visit_plan_views.xml',
        'views/fleet_vehicle_views.xml',
        'views/van_sales_menus.xml',
    ],
    'installable': True,
    'application': True,
}
