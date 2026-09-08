# Part of the Van Sales project.

from odoo import api, fields, models

from .product_category import VAN_STOCK_POLICIES


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    van_sale_stock_policy = fields.Selection(
        selection=[('category', "Use Category Policy")] + VAN_STOCK_POLICIES,
        string="Van Over-Sell Policy",
        required=True, default='category',
        help="Overrides the product category's van over-sell policy for this "
             "product only.")
    van_sale_stock_policy_effective = fields.Selection(
        selection=VAN_STOCK_POLICIES,
        string="Effective Policy",
        compute='_compute_van_sale_stock_policy_effective',
        help="The policy actually applied, after the category fallback.")

    @api.depends('van_sale_stock_policy', 'categ_id.van_sale_stock_policy')
    def _compute_van_sale_stock_policy_effective(self):
        for template in self:
            template.van_sale_stock_policy_effective = (
                template.categ_id.van_sale_stock_policy or 'warn'
                if template.van_sale_stock_policy == 'category'
                else template.van_sale_stock_policy)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    van_sale_stock_policy_effective = fields.Selection(
        selection=VAN_STOCK_POLICIES,
        string="Effective Policy",
        related='product_tmpl_id.van_sale_stock_policy_effective')
