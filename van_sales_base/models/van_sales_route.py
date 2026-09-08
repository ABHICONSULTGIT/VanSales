# Part of the Van Sales project.

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

STOP_TYPES = [
    ('customer', "Customer"),
    ('location', "Location"),
]


class VanSalesRoute(models.Model):
    """An ordered list of stops served by one van.

    The client runs two models side by side, and the route type says which one
    this route is:

    * **Customer route** - a fixed round of known shops. The salesman visits
      named accounts, which may buy on credit and receive statements.
    * **Location route** - the van parks at public places (a market, a labour
      camp) and sells to whoever walks up. The stops are places, not people.

    The type is a classification and a default, not a restriction: a line
    carries its own stop type, so a route that mixes a few known shops with a
    market stop is possible. Nothing in the requirement document says mixing is
    invalid, so it is not forbidden here.

    Visit frequency is deliberately absent - see the module README.
    """

    _name = 'van.sales.route'
    _inherit = ['mail.thread']
    _description = "Van Sales Route"
    _order = 'code, id'
    _check_company_auto = True

    name = fields.Char(
        string="Route Name", required=True, tracking=True)
    code = fields.Char(
        string="Route Code", required=True, copy=False, tracking=True,
        default=lambda self: _("New"),
        help="Short unique code for the route. Left as 'New' it is taken from "
             "the Van Sales Route sequence on save; type over it to use your "
             "own numbering.")
    route_type = fields.Selection(
        selection=[
            ('customer', "Customer Route"),
            ('location', "Location Route"),
        ],
        string="Route Type", required=True, default='customer', tracking=True,
        help="Customer Route: a fixed round of known shops.\n"
             "Location Route: the van parks at places and sells to walk-up "
             "buyers.\n"
             "This sets the default kind of stop and drives reporting; "
             "individual stops can still be of either kind.")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        comodel_name='res.company', string="Company",
        required=True, index=True,
        default=lambda self: self.env.company)
    van_id = fields.Many2one(
        comodel_name='fleet.vehicle', string="Van",
        domain="[('is_sales_van', '=', True)]",
        tracking=True, index='btree_not_null', check_company=True,
        ondelete='restrict')
    salesman_user_id = fields.Many2one(
        comodel_name='res.users', string="Salesman",
        related='van_id.salesman_user_id',
        store=True, readonly=True, index='btree_not_null',
        help="Derived from the van. The requirement document states a salesman "
             "is assigned to exactly one van at a time, so the van is the "
             "single source of truth and the route follows it.")
    van_location_id = fields.Many2one(
        comodel_name='stock.location', string="Van Stock Location",
        related='van_id.van_location_id', readonly=True)
    line_ids = fields.One2many(
        comodel_name='van.sales.route.line', inverse_name='route_id',
        string="Stops", copy=True)
    stop_count = fields.Integer(
        string="Stops", compute='_compute_stop_counts')
    customer_stop_count = fields.Integer(
        string="Customer Stops", compute='_compute_stop_counts')
    location_stop_count = fields.Integer(
        string="Location Stops", compute='_compute_stop_counts')
    note = fields.Html(string="Internal Notes")

    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        "A route with this code already exists for this company.",
    )

    # --------------------------------------------------------------------
    # Compute / display
    # --------------------------------------------------------------------
    @api.depends('line_ids.stop_type')
    def _compute_stop_counts(self):
        for route in self:
            lines = route.line_ids
            route.stop_count = len(lines)
            route.customer_stop_count = len(
                lines.filtered(lambda l: l.stop_type == 'customer'))
            route.location_stop_count = len(
                lines.filtered(lambda l: l.stop_type == 'location'))

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for route in self:
            route.display_name = (
                "%s - %s" % (route.code, route.name)
                if route.code and route.name
                else (route.name or route.code or "")
            )

    # --------------------------------------------------------------------
    # ORM overrides
    # --------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        """Take the route code from the sequence when it was left as 'New'.

        Assigned on save rather than on form open, so abandoned forms do not
        burn numbers. The sequence is 'standard', so the occasional gap from a
        rolled-back transaction is harmless.
        """
        for vals in vals_list:
            if vals.get('code', _("New")) == _("New"):
                company_id = vals.get('company_id') or self.env.company.id
                vals['code'] = self.env['ir.sequence'].with_company(
                    company_id).next_by_code('van.sales.route') or _("New")
        return super().create(vals_list)

    # --------------------------------------------------------------------
    # Constraints
    # --------------------------------------------------------------------
    @api.constrains('van_id')
    def _check_van_has_location(self):
        """A route is only operable once its van has a stock location.

        This is the point where the requirement actually bites, so it is
        enforced here rather than on the vehicle - which would otherwise stop
        anyone from ticking "Sales Van" before provisioning the location.
        """
        for route in self:
            if route.van_id and not route.van_id.van_location_id:
                raise ValidationError(_(
                    "Van %(van)s has no stock location yet, so it cannot be "
                    "assigned to route %(route)s. Create the van's stock "
                    "location first, from the vehicle form or from "
                    "Van Sales > Configuration > Vans.",
                    van=route.van_id.display_name,
                    route=route.display_name,
                ))

    @api.constrains('van_id', 'company_id')
    def _check_van_company(self):
        for route in self:
            van_company = route.van_id.company_id
            if van_company and van_company != route.company_id:
                raise ValidationError(_(
                    "Van %(van)s belongs to company %(other)s but route "
                    "%(route)s belongs to %(company)s.",
                    van=route.van_id.display_name,
                    other=van_company.display_name,
                    route=route.display_name,
                    company=route.company_id.display_name,
                ))

    # --------------------------------------------------------------------
    # Actions
    # --------------------------------------------------------------------
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

    def action_create_visit_plan(self):
        """Create today's plan for this route and open it."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        plan = self.env['van.sales.visit.plan'].search([
            ('route_id', '=', self.id),
            ('date', '=', today),
        ], limit=1)
        if not plan:
            # Stops are generated by van.sales.visit.plan.create().
            plan = self.env['van.sales.visit.plan'].create({
                'route_id': self.id,
                'date': today,
            })
        return {
            'type': 'ir.actions.act_window',
            'name': _("Visit Plan"),
            'res_model': 'van.sales.visit.plan',
            'view_mode': 'form',
            'res_id': plan.id,
        }


class VanSalesRouteLine(models.Model):
    """One stop on a route, in visiting order.

    A stop is either a named customer or a place. ``stop_type`` says which, and
    exactly one of ``partner_id`` / ``stop_location_id`` is filled to match.
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
    stop_type = fields.Selection(
        selection=STOP_TYPES, string="Stop Type",
        required=True, default='customer')
    partner_id = fields.Many2one(
        comodel_name='res.partner', string="Customer",
        index='btree_not_null', check_company=True, ondelete='restrict')
    stop_location_id = fields.Many2one(
        comodel_name='van.sales.stop.location', string="Stop Location",
        index='btree_not_null', check_company=True, ondelete='restrict')
    company_id = fields.Many2one(
        comodel_name='res.company', related='route_id.company_id',
        store=True, index=True)
    salesman_user_id = fields.Many2one(
        comodel_name='res.users', related='route_id.salesman_user_id',
        store=True, index='btree_not_null')
    stop_city = fields.Char(
        string="City", compute='_compute_stop_city')
    partner_phone = fields.Char(related='partner_id.phone', string="Phone")
    instruction = fields.Char(
        string="Instructions",
        help="Free text shown to the salesman for this stop.")

    # NULLs do not collide in a unique index, so each of these constrains only
    # the stop kind it applies to.
    _partner_route_uniq = models.Constraint(
        'UNIQUE(route_id, partner_id)',
        "This customer is already on this route.",
    )
    _location_route_uniq = models.Constraint(
        'UNIQUE(route_id, stop_location_id)',
        "This stop location is already on this route.",
    )

    # --------------------------------------------------------------------
    # Compute / onchange
    # --------------------------------------------------------------------
    @api.depends('partner_id', 'stop_location_id', 'stop_type')
    def _compute_stop_city(self):
        for line in self:
            line.stop_city = (
                line.partner_id.city if line.stop_type == 'customer'
                else line.stop_location_id.city)

    @api.depends('partner_id', 'stop_location_id', 'stop_type')
    def _compute_display_name(self):
        for line in self:
            target = (line.partner_id if line.stop_type == 'customer'
                      else line.stop_location_id)
            line.display_name = target.display_name or ""

    @api.onchange('stop_type')
    def _onchange_stop_type(self):
        """Clear the field that no longer applies, so no stale value lingers."""
        for line in self:
            if line.stop_type == 'customer':
                line.stop_location_id = False
            else:
                line.partner_id = False

    # --------------------------------------------------------------------
    # Constraints
    # --------------------------------------------------------------------
    @api.constrains('stop_type', 'partner_id', 'stop_location_id')
    def _check_stop_target(self):
        for line in self:
            if line.stop_type == 'customer':
                if not line.partner_id:
                    raise ValidationError(_(
                        "A customer stop needs a customer. Set one on the "
                        "stop of route %s.", line.route_id.display_name))
                if line.stop_location_id:
                    raise ValidationError(_(
                        "A customer stop cannot also carry a stop location."))
            else:
                if not line.stop_location_id:
                    raise ValidationError(_(
                        "A location stop needs a stop location. Set one on "
                        "the stop of route %s.", line.route_id.display_name))
                if line.partner_id:
                    raise ValidationError(_(
                        "A location stop cannot also carry a customer."))
