# Part of the Van Sales project.

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class VanSalesVisitPlan(models.Model):
    """One day's stop list for one route.

    Plans are created explicitly (per route, per date) and populated from the
    route's customer list. There is no automatic generator yet: that needs the
    visit frequency model, which the requirement document leaves undefined.
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
    route_id = fields.Many2one(
        comodel_name='van.sales.route', string="Route",
        required=True, index=True, tracking=True,
        check_company=True, ondelete='restrict')
    van_id = fields.Many2one(
        comodel_name='fleet.vehicle', string="Van",
        related='route_id.van_id', store=True, index='btree_not_null')
    salesman_user_id = fields.Many2one(
        comodel_name='res.users', string="Salesman",
        related='route_id.salesman_user_id', store=True,
        index='btree_not_null')
    company_id = fields.Many2one(
        comodel_name='res.company', related='route_id.company_id',
        store=True, index=True)
    state = fields.Selection(
        selection=[
            ('draft', "Draft"),
            ('in_progress', "In Progress"),
            ('done', "Done"),
            ('cancel', "Cancelled"),
        ],
        string="Status", default='draft', required=True,
        tracking=True, copy=False)
    visit_ids = fields.One2many(
        comodel_name='van.sales.visit', inverse_name='plan_id',
        string="Visits")
    visit_count = fields.Integer(
        string="Planned", compute='_compute_visit_counts')
    visit_done_count = fields.Integer(
        string="Completed", compute='_compute_visit_counts')
    visit_pending_count = fields.Integer(
        string="Pending", compute='_compute_visit_counts')

    _route_date_uniq = models.Constraint(
        'UNIQUE(route_id, date)',
        "A visit plan already exists for this route on this date.",
    )

    # --------------------------------------------------------------------
    # Compute
    # --------------------------------------------------------------------
    @api.depends('route_id.code', 'date')
    def _compute_name(self):
        for plan in self:
            if plan.route_id and plan.date:
                plan.name = "%s / %s" % (
                    plan.route_id.code, fields.Date.to_string(plan.date))
            else:
                plan.name = False

    @api.depends('visit_ids.state')
    def _compute_visit_counts(self):
        for plan in self:
            visits = plan.visit_ids
            plan.visit_count = len(visits)
            plan.visit_done_count = len(
                visits.filtered(lambda v: v.state == 'done'))
            plan.visit_pending_count = len(
                visits.filtered(lambda v: v.state in ('planned', 'checked_in')))

    # --------------------------------------------------------------------
    # ORM overrides
    # --------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        """Populate the stop list straight away.

        A plan without stops is not usable, and the rule used here is exactly
        the rule the Generate Stops button uses - every customer on the route,
        in route order. No scheduling assumption is introduced.

        Pass ``van_sales_no_visit_generation`` in the context to skip it, for
        data imports or a plan that is to be filled in by hand.
        """
        plans = super().create(vals_list)
        if not self.env.context.get('van_sales_no_visit_generation'):
            plans.filtered(
                lambda p: p.state == 'draft' and p.route_id.line_ids
            )._generate_visits()
        return plans

    def unlink(self):
        blocked = self.filtered(lambda p: p.state not in ('draft', 'cancel'))
        if blocked:
            raise UserError(_(
                "A visit plan can only be deleted while it is draft or "
                "cancelled. Cancel these plans first: %s",
                ", ".join(blocked.mapped('display_name')),
            ))
        return super().unlink()

    # --------------------------------------------------------------------
    # Actions
    # --------------------------------------------------------------------
    def _generate_visits(self):
        """Create one stop per route customer that is not already planned.

        Non-raising, so it can run from ``create()`` without blocking a plan
        for a route that has no customers yet. Idempotent: existing stops are
        left untouched, so a customer added to the route later can be pulled
        in without disturbing visits already in progress.
        """
        Visit = self.env['van.sales.visit']
        created = Visit
        for plan in self:
            if plan.state in ('done', 'cancel'):
                continue
            planned = {
                (v.stop_type, v.partner_id.id, v.stop_location_id.id)
                for v in plan.visit_ids
            }
            values = [
                {
                    'plan_id': plan.id,
                    'stop_type': line.stop_type,
                    'partner_id': line.partner_id.id,
                    'stop_location_id': line.stop_location_id.id,
                    'sequence': line.sequence,
                }
                for line in plan.route_id.line_ids
                if (line.stop_type, line.partner_id.id,
                    line.stop_location_id.id) not in planned
            ]
            if values:
                created |= Visit.create(values)
        return created

    def action_generate_visits(self):
        """Button version: says why nothing happened instead of staying silent."""
        for plan in self:
            if plan.state in ('done', 'cancel'):
                raise UserError(_(
                    "Plan %s is %s, so its visits cannot be regenerated.",
                    plan.display_name, plan.state))
            if not plan.route_id.line_ids:
                raise UserError(_(
                    "Route %s has no stops, so there is nothing to plan.",
                    plan.route_id.display_name))
        return self._generate_visits()

    def action_start(self):
        for plan in self:
            if plan.state != 'draft':
                raise UserError(_(
                    "Only a draft plan can be started. %s is %s.",
                    plan.display_name, plan.state))
            if not plan.visit_ids:
                raise UserError(_(
                    "Plan %s has no visits yet. Generate the stop list first.",
                    plan.display_name))
        self.write({'state': 'in_progress'})

    def action_done(self):
        for plan in self:
            if plan.state != 'in_progress':
                raise UserError(_(
                    "Only a plan in progress can be closed. %s is %s.",
                    plan.display_name, plan.state))
            open_visits = plan.visit_ids.filtered(
                lambda v: v.state == 'checked_in')
            if open_visits:
                raise UserError(_(
                    "Check out of these stops before closing the plan: %s",
                    ", ".join(v.display_name for v in open_visits),
                ))
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_draft(self):
        for plan in self:
            if plan.state != 'cancel':
                raise UserError(_(
                    "Only a cancelled plan can be reset to draft. %s is %s.",
                    plan.display_name, plan.state))
        self.write({'state': 'draft'})

    def action_view_visits(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Visits"),
            'res_model': 'van.sales.visit',
            'view_mode': 'list,form',
            'domain': [('plan_id', '=', self.id)],
            'context': {'default_plan_id': self.id},
        }
