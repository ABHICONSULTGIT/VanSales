# Part of the Van Sales project.
{
    'name': "Van Sales - Stock",
    'summary': "Van loading, unloading and end-of-day stock reconciliation",
    'description': """
Van Sales - Stock
=================

Second module of the Van Sales suite. It turns the van stock locations created
by *Van Sales - Base* into a working stock flow:

* **Van loads and returns** - ordinary Odoo internal transfers, recognised
  automatically as van operations from their source and destination locations.
  No parallel document model, so valuation, traceability and reporting stay
  standard.
* **Discrepancy capture** - short or over receipt is the difference Odoo
  already records between demand and done quantity; this adds the reason.
* **Over-sell policy** - Odoo 19 has no negative-stock setting of any kind, so
  the "prevent or warn on selling beyond van stock, configurable per product"
  requirement is implemented here as a policy plus a checking service. The
  enforcement point lives in the sales module.
* **Van stock count** - System, Counted and Difference per product. Applying
  corrects the van as a standard inventory adjustment; one button then raises
  the return of the counted stock as an ordinary draft transfer.
""",
    'author': "BizTech Computers",
    'website': "https://biztechbh.biz/",
    'category': 'Inventory/Van Sales',
    'version': '19.0.2.1.0',
    'license': 'OPL-1',
    'depends': [
        'van_sales_base',
        'stock',
    ],
    'data': [
        'security/van_sales_stock_groups.xml',
        'security/ir.model.access.csv',
        'security/van_sales_stock_security.xml',
        'data/van_sales_stock_data.xml',
        'views/product_views.xml',
        'views/stock_picking_views.xml',
        'views/van_sales_reconciliation_views.xml',
        'views/fleet_vehicle_views.xml',
        'views/van_sales_stock_menus.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
