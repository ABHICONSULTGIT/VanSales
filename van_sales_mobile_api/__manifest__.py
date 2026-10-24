# Part of the Van Sales project.
{
    'name': "Van Sales - Mobile API",
    'summary': "REST API for the salesperson mobile app",
    'description': """
Van Sales - Mobile API
======================

Everything a van salesman does in the field, over plain JSON:
login, dashboard, customers, van and warehouse stock, today's visit plan,
sale orders (confirm, deliver, invoice), payments, load and return requests,
and stock counts.

* Bearer-token authentication. Tokens are stored hashed, expire after 30 days
  and are revoked on logout or password change.
* Every request runs as the salesman, so Odoo's own access rules decide what
  he sees. The few places that need more (creating his own customers, issuing
  invoices for his own orders) are guarded in code.
* One response envelope: success, message, data, error, pagination.
""",
    'author': "BizTech Computers",
    'website': "https://biztechbh.biz/",
    'category': 'Sales/Van Sales',
    'version': '19.0.1.0.0',
    'license': 'OPL-1',
    'depends': [
        'van_sales_sale',
        'auth_signup',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
    ],
    'installable': True,
    'application': False,
}
