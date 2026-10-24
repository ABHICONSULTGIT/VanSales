# Part of the Van Sales project.

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class VanSalesVisit(models.Model):
    """One line of a visit plan: a customer, a place, or both.

    Its only job is to carry a sale - ``van_sales_sale`` adds the sale order.
    A line comes from the plan's route (a stop the salesman is expected to
    cover) or from a sale he made off the route; either way it is the same
    record, and nothing here restricts where he goes.
    """

    _name = 'van.sales.visit'
    _description = "Van Sales Visit"
    _order = 'date desc, sequence, id'
    _check_company_auto = True

    name = fields.Char(
        string="Reference", compute='_compute_name', store=True)
    plan_id = fields.Many2one(
        comodel_name='van.sales.visit.plan', string="Visit Plan",
        required=True, index=True, ondelete='cascade', check_company=True)
    sequence = fields.Integer(string="Sequence", default=10)
    partner_id = fields.Many2one(
        comodel_name='res.partner', string="Customer",
        index='btree_not_null', check_company=True, ondelete='restrict')
    stop_location_id = fields.Many2one(
        comodel_name='van.sales.stop.location', string="Stop Location",
        index='btree_not_null', check_company=True, ondelete='restrict')

    # Copied from the plan and stored, for record rules and searching. Never
    # edited on the line itself.
    date = fields.Date(
        string="Date", related='plan_id.date', store=True, index=True)
    salesman_user_id = fields.Many2one(
        comodel_name='res.users', string="Salesman",
        related='plan_id.salesman_user_id', store=True,
        index='btree_not_null')
    van_id = fields.Many2one(
        comodel_name='fleet.vehicle', string="Van",
        related='plan_id.van_id', store=True, index='btree_not_null')
    company_id = fields.Many2one(
        comodel_name='res.company', related='plan_id.company_id',
        store=True, index=True)

    @api.depends('partner_id', 'stop_location_id', 'date')
    def _compute_name(self):
        for visit in self:
            target = (visit.partner_id.display_name
                      or visit.stop_location_id.display_name or "")
            if target and visit.date:
                visit.name = "%s / %s" % (
                    target, fields.Date.to_string(visit.date))
            else:
                visit.name = target or False

    # 'plan_id' is listed so the check also runs on create: Odoo only fires a
    # constraint when one of its fields is written, and a line created
    # empty writes neither the customer nor the location.
    @api.constrains('plan_id', 'partner_id', 'stop_location_id')
    def _check_stop_target(self):
        for visit in self:
            if not (visit.partner_id or visit.stop_location_id):
                raise ValidationError(_(
                    "A visit needs a customer, a stop location, or both."))
