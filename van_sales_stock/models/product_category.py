# Part of the Van Sales project.

from odoo import fields, models

VAN_STOCK_POLICIES = [
    ('allow', "Allow"),
    ('warn', "Warn"),
    ('block', "Block"),
]


class ProductCategory(models.Model):
    _inherit = 'product.category'

    van_sale_stock_policy = fields.Selection(
        selection=VAN_STOCK_POLICIES,
        string="Van Over-Sell Policy",
        required=True, default='warn',
        help="What happens when a salesman tries to sell more of a product in "
             "this category than the van is carrying.\n"
             "Allow: sell anyway, van stock goes negative.\n"
             "Warn: sell, but tell the salesman.\n"
             "Block: refuse the line.\n"
             "Odoo has no negative-stock setting of its own, so this policy is "
             "the only control. Individual products can override it.")
