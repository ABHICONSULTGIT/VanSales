# Part of the Van Sales project.

import psycopg2

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class VanSalesVisitPlan(models.Model):
    """One salesman's day.

    The base of a plan is the salesman and his van. A route is optional: when
    one is set, its stops are copied in as the checklist of places he is
    expected to cover today. It never restricts him - every sale he makes that
    day, on the route or off it, is added to the same plan automatically (see
    ``van_sales_sale``).
    """

    _name = 'van.sales.visit.plan'
    _inherit = ['mail.thread']
    _description = "Van Sales Daily Visit Plan"
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string="Reference", compute='_compute_name', store=True)
    date = fields.Date(
        string="Date", required=True, index=True, tracking=True,
        default=fields.Date.context_today)
    salesman_user_id = fields.Many2one(
        comodel_name='res.users', string="Salesman",
        required=True, index=True, tracking=True,
        domain="[('share', '=', False)]",
        default=lambda self: self.env.user)
    van_id = fields.Many2one(
        comodel_name='fleet.vehicle', string="Van",
        compute='_compute_van_id', store=True, readonly=True,
        index='btree_not_null',
        help="The van this salesman drives. Kept as it was on the day if he "
             "later moves to another van.")
    route_id = fields.Many2one(
        comodel_name='van.sales.route', string="Route",
        index='btree_not_null', tracking=True,
        check_company=True, ondelete='restrict',
        help="Optional. Its stops are added to the plan as today's checklist. "
             "The salesman can still sell anywhere.")
    company_id = fields.Many2one(
        comodel_name='res.company', string="Company",
        required=True, index=True,
        default=lambda self: self.env.company)
    visit_ids = fields.One2many(
        comodel_name='van.sales.visit', inverse_name='plan_id',
        string="Visits")

    _salesman_date_uniq = models.Constraint(
        'UNIQUE(salesman_user_id, date)',
        "This salesman already has a visit plan for this date.",
    )

    # --------------------------------------------------------------------
    # Compute
    # --------------------------------------------------------------------
    @api.depends('salesman_user_id', 'date')
    def _compute_name(self):
        for plan in self:
            if plan.salesman_user_id and plan.date:
                plan.name = "%s / %s" % (
                    plan.salesman_user_id.name,
                    fields.Date.to_string(plan.date))
            else:
                plan.name = False

    @api.depends('salesman_user_id')
    def _compute_van_id(self):
        Vehicle = self.env['fleet.vehicle']
        for plan in self:
            plan.van_id = Vehicle._van_sales_van_of(plan.salesman_user_id)

    # --------------------------------------------------------------------
    # Constraints
    # --------------------------------------------------------------------
    @api.constrains('salesman_user_id', 'van_id')
    def _check_salesman_has_van(self):
        for plan in self:
            if plan.salesman_user_id and not plan.van_id:
                raise ValidationError(_(
                    "%s does not drive a sales van, so a visit plan cannot be "
                    "made for him. Assign him to a van in Van Sales > "
                    "Configuration > Sales Vans first.",
                    plan.salesman_user_id.display_name))

    # --------------------------------------------------------------------
    # ORM overrides
    # --------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        plans = super().create(vals_list)
        if not self.env.context.get('van_sales_no_visit_generation'):
            plans.filtered('route_id')._generate_visits()
        return plans

    def write(self, vals):
        result = super().write(vals)
        # A route can be given to the salesman at any point in the day.
        if vals.get('route_id') \
                and not self.env.context.get('van_sales_no_visit_generation'):
            self._generate_visits()
        return result

    # --------------------------------------------------------------------
    # Route stops
    # --------------------------------------------------------------------
    @staticmethod
    def _van_sales_stop_key(partner, location):
        """A stop is identified by its customer when it has one, else its place.

        Matching on the customer alone is deliberate: if he was already sold to
        earlier in the day, his route stop counts as covered - even though that
        sale's line was created without the stop location.
        """
        return ('partner', partner.id) if partner else ('location', location.id)

    def _generate_visits(self):
        """Add the route's stops that are not on the plan yet. Idempotent."""
        Visit = self.env['van.sales.visit']
        created = Visit
        for plan in self.filtered('route_id'):
            existing = {
                self._van_sales_stop_key(v.partner_id, v.stop_location_id): v
                for v in plan.visit_ids
            }
            values = []
            for line in plan.route_id.line_ids:
                key = self._van_sales_stop_key(
                    line.partner_id, line.stop_location_id)
                visit = existing.get(key)
                if visit:
                    # Fill in the place on a stop that was added before the
                    # route, so the checklist shows it.
                    if line.stop_location_id and not visit.stop_location_id:
                        visit.stop_location_id = line.stop_location_id
                    continue
                values.append({
                    'plan_id': plan.id,
                    'sequence': line.sequence,
                    'partner_id': line.partner_id.id,
                    'stop_location_id': line.stop_location_id.id,
                })
            if values:
                created |= Visit.create(values)
        return created

    def action_generate_visits(self):
        """Button version: says why nothing happened instead of staying silent."""
        for plan in self:
            if not plan.route_id:
                raise UserError(_(
                    "Plan %s has no route, so there are no stops to load.",
                    plan.display_name))
            if not plan.route_id.line_ids:
                raise UserError(_(
                    "Route %s has no stops.", plan.route_id.display_name))
        self._generate_visits()
        return True

    # --------------------------------------------------------------------
    # Used by the sale order hook
    # --------------------------------------------------------------------
    @api.model
    def _van_sales_get_or_create(self, user, date, company):
        """The plan for ``user`` on ``date``, created if it does not exist.

        Race-safe: two orders saved at the same moment for the same salesman
        would both find no plan and both try to create one. The second create
        hits the unique constraint inside a savepoint, which is rolled back,
        and the plan the first one created is returned instead.

        sudo: the caller may be an office user with no Van Sales rights
        creating an order on the salesman's behalf.
        """
        Plan = self.sudo()
        domain = [('salesman_user_id', '=', user.id), ('date', '=', date)]
        plan = Plan.search(domain, limit=1)
        if plan:
            return plan
        try:
            with self.env.cr.savepoint():
                return Plan.create({
                    'salesman_user_id': user.id,
                    'date': date,
                    'company_id': company.id,
                })
        except psycopg2.errors.UniqueViolation:
            self.env.invalidate_all()
            return Plan.search(domain, limit=1)
