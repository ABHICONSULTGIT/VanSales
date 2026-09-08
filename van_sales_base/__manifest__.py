# Part of the Van Sales project.
{
    'name': "Van Sales - Base",
    'summary': "Van, route and visit master data for route-based van sales",
    'description': """
Van Sales - Base
================

Foundation module of the Van Sales suite. It provides the master data every
other van sales module builds on:

* **Van master** - extends ``fleet.vehicle`` rather than duplicating it. Adds
  the van's stock location, its salesman, its cash journal and its routes.
* **Van stock location provisioning** - a wizard that creates one internal
  child location per van under a warehouse. Deliberately *not* one warehouse
  per van: a warehouse would create eight picking types and eight sequences
  each, and gives nothing a child internal location does not.
* **Routes** - an ordered list of customers served by a van.
* **Daily visit plans and visits** - check in / check out with GPS capture and
  visit duration.
* **Security** - three roles (User / Supervisor / Administrator) with record
  rules scoping a salesman to their own van.

Deliberately out of scope in this module: visit frequency scheduling
(pending confirmation of the frequency model from the client), van stock
operations, the order-to-cash flow and the mobile synchronisation API.
Those live in the later modules of the suite.
""",
    'author': "BizTech Computers",
    'website': "https://biztechbh.biz/",
    'category': 'Inventory/Van Sales',
    'version': '19.0.1.2.0',
    'license': 'OPL-1',
    'depends': [
        'base',
        'mail',
        'stock',
        'fleet',
        'account',
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
