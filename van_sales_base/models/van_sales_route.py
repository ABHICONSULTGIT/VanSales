# Part of the Van Sales project.

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class VanSalesRoute(models.Model):
    """A reusable list of stops - a guideline, never a restriction.

    A route belongs to no van and no salesman. It is handed to a salesman for
    a particular day on his Visit Plan, where its stops become the checklist of
    places he is expected to cover. He remains free to sell to anyone else.
    """

    _name = 'van.sales.route'
    _inherit = ['mail.thread']
    _description = "Van Sales Route"
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char(
        string="Route Name", required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        comodel_name='res.company', string="Company",
        required=True, index=True,
        default=lambda self: self.env.company)
    line_ids = fields.One2many(
        comodel_name='van.sales.route.line', inverse_name='route_id',
        string="Stops", copy=True)
    note = fields.Html(string="Internal Notes")

    def action_view_visit_plans(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Visit Plans"),
            'res_model': 'van.sales.visit.plan',
            'view_mode': 'list,form',
            'domain': [('route_id', '=', self.id)],
            'context': {'default_route_id': self.id},
        }


class VanSalesRouteLine(models.Model):
    """One stop on a route, in visiting order.

    A stop can name a customer, a stop location, or both - a shop at the
    Friday Market is the customer *and* the place. At least one is required.
    """

    _name = 'van.sales.route.line'
    _description = "Van Sales Route Stop"
    _order = 'route_id, sequence, id'
    _check_company_auto = True

    route_id = fields.Many2one(
        comodel_name='van.sales.route', string="Route",
        required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(
        string="Sequence", default=10,
        help="Order in which the stop is visited along the route.")
    partner_id = fields.Many2one(
        comodel_name='res.partner', string="Customer",
        index='btree_not_null', check_company=True, ondelete='restrict')
    stop_location_id = fields.Many2one(
        comodel_name='van.sales.stop.location', string="Stop Location",
        index='btree_not_null', check_company=True, ondelete='restrict')
    company_id = fields.Many2one(
        comodel_name='res.company', related='route_id.company_id',
        store=True, index=True)
    instruction = fields.Char(
        string="Instructions",
        help="Free text shown to the salesman for this stop - why it matters "
             "today, what to bring, who to ask for.")

    # A NULL partner does not collide, so location-only stops are unaffected.
    _partner_route_uniq = models.Constraint(
        'UNIQUE(route_id, partner_id)',
        "This customer is already on this route.",
    )

    @api.depends('partner_id', 'stop_location_id')
    def _compute_display_name(self):
        for line in self:
            names = [n for n in (line.partner_id.display_name,
                                 line.stop_location_id.display_name) if n]
            line.display_name = " @ ".join(names)

    # 'route_id' is listed so the check also runs on create: Odoo only fires a
    # constraint when one of its fields is written, and a line created
    # empty writes neither the customer nor the location.
    @api.constrains('route_id', 'partner_id', 'stop_location_id')
    def _check_stop_target(self):
        for line in self:
            if not (line.partner_id or line.stop_location_id):
                raise ValidationError(_(
                    "A stop on route %s needs a customer, a stop location, or "
                    "both.", line.route_id.display_name))
