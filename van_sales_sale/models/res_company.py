# Part of the Van Sales project.

from odoo import fields, models

CREDIT_POLICIES = [
    ('allow', "Allow"),
    ('warn', "Warn"),
    ('block', "Block"),
]


class ResCompany(models.Model):
    _inherit = 'res.company'

    van_sale_credit_policy = fields.Selection(
        selection=CREDIT_POLICIES,
        string="Van Credit Limit Policy",
        required=True, default='warn',
        help="What happens when a van order would take a customer past their "
             "credit limit.\n"
             "Allow: confirm silently.\n"
             "Warn: confirm, but record it on the order.\n"
             "Block: refuse to confirm.\n"
             "Odoo itself only ever warns - there is no hard credit block "
             "anywhere in the product - so this policy is the only control.")


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    van_sale_credit_policy = fields.Selection(
        related='company_id.van_sale_credit_policy', readonly=False)
