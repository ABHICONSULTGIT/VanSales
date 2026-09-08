# Part of the Van Sales project.
{
    'name': "Van Sales - Sale",
    'summary': "Selling from the van: orders, deliveries, invoices and cash collection",
    'description': """
Van Sales - Sale
================

Third module of the Van Sales suite. Turns a customer visit into an order that
ships **from the van's own stock**, invoices, and gets paid on the spot.

* **Delivery from the van, not the warehouse.** Each van gets its own delivery
  route whose rule sources from the van's stock location. Odoo's own
  procurement then does the rest, so quantity delivered, invoice status,
  backorders and returns all behave exactly as standard - no core overrides.
* **Sell from a visit.** One action on a customer stop raises the order with the
  customer, van, route, visit and van delivery route already set.
* **Over-sell enforcement.** The policy configured in *Van Sales - Stock* is
  applied here, at order confirmation, because this is where a line is actually
  sold.
* **Credit policy.** Odoo only ever warns about a credit limit - there is no
  hard block anywhere in the product. A company-level policy turns that warning
  into a block when the business wants one.
* **Cash collection.** One receipt, several invoices, an explicit amount against
  each. Odoo's own reconciliation is first-in-first-out by due date and cannot
  split a collection the way a salesman does, so allocation is explicit here.

Deliberately not included, because the answers are not in: free-of-charge
goods, returns and credit notes, end-of-day cash hand-in, and the identity of
a walk-up buyer on a location route. See the README.
""",
    'author': "BizTech Computers",
    'website': "https://biztechbh.biz/",
    'category': 'Sales/Van Sales',
    'version': '19.0.1.0.0',
    'license': 'OPL-1',
    'depends': [
        'van_sales_stock',
        'sale_management',
        'sale_stock',
        'account',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/van_sales_sale_security.xml',
        'data/van_sales_sale_data.xml',
        'views/res_config_settings_views.xml',
        'views/sale_order_views.xml',
        'views/account_move_views.xml',
        'views/van_sales_collection_views.xml',
        'views/van_sales_visit_views.xml',
        'views/fleet_vehicle_views.xml',
        'views/van_sales_sale_menus.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
