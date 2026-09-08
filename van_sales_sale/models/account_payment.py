# Part of the Van Sales project.

from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    van_id = fields.Many2one(
        comodel_name='fleet.vehicle', string="Van",
        domain="[('is_sales_van', '=', True)]",
        check_company=True, index='btree_not_null', copy=False)
    van_visit_id = fields.Many2one(
        comodel_name='van.sales.visit', string="Visit",
        index='btree_not_null', check_company=True, copy=False)
    van_collection_id = fields.Many2one(
        comodel_name='van.sales.collection', string="Collection",
        index='btree_not_null', copy=False, ondelete='set null',
        help="The receipt this payment was part of. One receipt can settle "
             "several invoices, and each gets its own payment.")
    van_salesman_user_id = fields.Many2one(
        comodel_name='res.users', string="Van Salesman",
        related='van_id.salesman_user_id', store=True,
        index='btree_not_null')
    van_client_uuid = fields.Char(
        string="Client Reference", copy=False, index='btree_not_null')

    _van_client_uuid_uniq = models.Constraint(
        'UNIQUE(van_client_uuid)',
        "A payment with this client reference already exists.",
    )
