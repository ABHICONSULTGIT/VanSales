# Part of the Van Sales project.

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .van_sales_route import STOP_TYPES


class VanSalesVisit(models.Model):
    """One customer stop: check in, do business, check out.

    This is the record the map view, the coverage report and - in the later
    modules - the orders, invoices and payments raised during the stop all
    hang off.
    """

    _name = 'van.sales.visit'
    _inherit = ['mail.thread']
    _description = "Van Sales Customer Visit"
    _order = 'date desc, sequence, id'
    _check_company_auto = True

    name = fields.Char(
        string="Reference", compute='_compute_name', store=True)
    plan_id = fields.Many2one(
        comodel_name='van.sales.visit.plan', string="Visit Plan",
        required=True, index=True, ondelete='cascade', check_company=True)
    sequence = fields.Integer(string="Sequence", default=10)
    stop_type = fields.Selection(
        selection=STOP_TYPES, string="Stop Type",
        required=True, default='customer')
    partner_id = fields.Many2one(
        comodel_name='res.partner', string="Customer",
        index='btree_not_null', check_company=True, ondelete='restrict')
    stop_location_id = fields.Many2one(
        comodel_name='van.sales.stop.location', string="Stop Location",
        index='btree_not_null', check_company=True, ondelete='restrict')
    stop_city = fields.Char(string="City", compute='_compute_stop_city')
    date = fields.Date(
        string="Date", related='plan_id.date', store=True, index=True)
    route_id = fields.Many2one(
        comodel_name='van.sales.route', string="Route",
        related='plan_id.route_id', store=True, index=True)
    van_id = fields.Many2one(
        comodel_name='fleet.vehicle', string="Van",
        related='plan_id.van_id', store=True, index='btree_not_null')
    salesman_user_id = fields.Many2one(
        comodel_name='res.users', string="Salesman",
        related='plan_id.salesman_user_id', store=True,
        index='btree_not_null')
    company_id = fields.Many2one(
        comodel_name='res.company', related='plan_id.company_id',
        store=True, index=True)
    state = fields.Selection(
        selection=[
            ('planned', "Planned"),
            ('checked_in', "Checked In"),
            ('done', "Done"),
            ('skipped', "Skipped"),
        ],
        string="Status", default='planned', required=True,
        tracking=True, copy=False)
    is_adhoc = fields.Boolean(
        string="Unplanned Visit", default=False,
        help="A stop that was not on the route: added by the salesman in the "
             "field.")
    adhoc_reason = fields.Char(
        string="Reason for Unplanned Visit")
    skip_reason = fields.Char(
        string="Reason for Skipping")

    check_in_datetime = fields.Datetime(
        string="Check In", copy=False, readonly=True, tracking=True)
    check_out_datetime = fields.Datetime(
        string="Check Out", copy=False, readonly=True, tracking=True)
    check_in_latitude = fields.Float(
        string="Check In Latitude", digits=(10, 7), copy=False, readonly=True)
    check_in_longitude = fields.Float(
        string="Check In Longitude", digits=(10, 7), copy=False, readonly=True)
    check_out_latitude = fields.Float(
        string="Check Out Latitude", digits=(10, 7), copy=False, readonly=True)
    check_out_longitude = fields.Float(
        string="Check Out Longitude", digits=(10, 7), copy=False, readonly=True)
    duration_minutes = fields.Float(
        string="Duration (minutes)", compute='_compute_duration_minutes',
        store=True, digits=(10, 2))

    _check_in_latitude_range = models.Constraint(
        'CHECK(check_in_latitude >= -90 AND check_in_latitude <= 90)',
        "Check-in latitude must be between -90 and 90 degrees.",
    )
    _check_in_longitude_range = models.Constraint(
        'CHECK(check_in_longitude >= -180 AND check_in_longitude <= 180)',
        "Check-in longitude must be between -180 and 180 degrees.",
    )
    _check_out_latitude_range = models.Constraint(
        'CHECK(check_out_latitude >= -90 AND check_out_latitude <= 90)',
        "Check-out latitude must be between -90 and 90 degrees.",
    )
    _check_out_longitude_range = models.Constraint(
        'CHECK(check_out_longitude >= -180 AND check_out_longitude <= 180)',
        "Check-out longitude must be between -180 and 180 degrees.",
    )

    # --------------------------------------------------------------------
    # Compute
    # --------------------------------------------------------------------
    def _stop_target(self):
        """The customer or the place, whichever this stop is."""
        self.ensure_one()
        return (self.partner_id if self.stop_type == 'customer'
                else self.stop_location_id)

    @api.depends('partner_id', 'stop_location_id', 'stop_type', 'date')
    def _compute_name(self):
        for visit in self:
            target = visit._stop_target().display_name or ""
            if target and visit.date:
                visit.name = "%s / %s" % (
                    target, fields.Date.to_string(visit.date))
            else:
                visit.name = target or False

    @api.depends('partner_id', 'stop_location_id', 'stop_type')
    def _compute_stop_city(self):
        for visit in self:
            visit.stop_city = (
                visit.partner_id.city if visit.stop_type == 'customer'
                else visit.stop_location_id.city)

    @api.onchange('stop_type')
    def _onchange_stop_type(self):
        for visit in self:
            if visit.stop_type == 'customer':
                visit.stop_location_id = False
            else:
                visit.partner_id = False

    @api.depends('check_in_datetime', 'check_out_datetime')
    def _compute_duration_minutes(self):
        for visit in self:
            if visit.check_in_datetime and visit.check_out_datetime:
                delta = visit.check_out_datetime - visit.check_in_datetime
                visit.duration_minutes = delta.total_seconds() / 60.0
            else:
                visit.duration_minutes = 0.0

    # --------------------------------------------------------------------
    # Constraints
    # --------------------------------------------------------------------
    @api.constrains('check_in_datetime', 'check_out_datetime')
    def _check_visit_times(self):
        for visit in self:
            if (visit.check_in_datetime and visit.check_out_datetime
                    and visit.check_out_datetime < visit.check_in_datetime):
                raise UserError(_(
                    "Check-out cannot be earlier than check-in on visit %s.",
                    visit.display_name))

    @api.constrains('stop_type', 'partner_id', 'stop_location_id')
    def _check_stop_target(self):
        for visit in self:
            if visit.stop_type == 'customer':
                if not visit.partner_id:
                    raise ValidationError(_(
                        "A customer stop needs a customer."))
                if visit.stop_location_id:
                    raise ValidationError(_(
                        "A customer stop cannot also carry a stop location."))
            else:
                if not visit.stop_location_id:
                    raise ValidationError(_(
                        "A location stop needs a stop location."))
                if visit.partner_id:
                    raise ValidationError(_(
                        "A location stop cannot also carry a customer."))

    @api.constrains('is_adhoc', 'adhoc_reason')
    def _check_adhoc_reason(self):
        for visit in self:
            if visit.is_adhoc and not (visit.adhoc_reason or "").strip():
                raise UserError(_(
                    "An unplanned visit needs a reason. Fill it in on visit %s.",
                    visit.display_name))

    # --------------------------------------------------------------------
    # Actions
    # --------------------------------------------------------------------
    def _set_position(self, prefix, latitude, longitude):
        """Store a GPS fix if one was supplied.

        Coordinates arrive from the context so the same action can be called
        from the backend (no fix) and, later, from the mobile API (with a fix).
        """
        values = {}
        if latitude is not None:
            values['%s_latitude' % prefix] = latitude
        if longitude is not None:
            values['%s_longitude' % prefix] = longitude
        return values

    def action_check_in(self):
        context = self.env.context
        latitude = context.get('van_sales_latitude')
        longitude = context.get('van_sales_longitude')
        for visit in self:
            if visit.state != 'planned':
                raise UserError(_(
                    "Only a planned stop can be checked into. %(visit)s is "
                    "%(state)s.",
                    visit=visit.display_name, state=visit.state))
            if visit.plan_id.state == 'draft':
                # Checking into the first stop starts the day. Logged on the
                # plan so the state change is visible, never silent.
                visit.plan_id.action_start()
                visit.plan_id.message_post(body=_(
                    "Plan started automatically on check-in at %s.",
                    visit.partner_id.display_name))
            elif visit.plan_id.state != 'in_progress':
                raise UserError(_(
                    "Plan %(plan)s is %(state)s, so its stops cannot be "
                    "visited.",
                    plan=visit.plan_id.display_name,
                    state=visit.plan_id.state))
            values = {
                'state': 'checked_in',
                'check_in_datetime': fields.Datetime.now(),
            }
            values.update(
                visit._set_position('check_in', latitude, longitude))
            visit.write(values)

    def action_check_out(self):
        context = self.env.context
        latitude = context.get('van_sales_latitude')
        longitude = context.get('van_sales_longitude')
        for visit in self:
            if visit.state != 'checked_in':
                raise UserError(_(
                    "Only a stop that has been checked into can be checked out "
                    "of. %(visit)s is %(state)s.",
                    visit=visit.display_name, state=visit.state))
            values = {
                'state': 'done',
                'check_out_datetime': fields.Datetime.now(),
            }
            values.update(
                visit._set_position('check_out', latitude, longitude))
            visit.write(values)

    def action_skip(self):
        for visit in self:
            if visit.state not in ('planned', 'checked_in'):
                raise UserError(_(
                    "%(visit)s is %(state)s and cannot be skipped.",
                    visit=visit.display_name, state=visit.state))
            if not (visit.skip_reason or "").strip():
                raise UserError(_(
                    "Give a reason before skipping %s.", visit.display_name))
            visit.write({'state': 'skipped'})

    def action_reset_to_planned(self):
        for visit in self:
            if visit.state == 'planned':
                continue
            visit.write({
                'state': 'planned',
                'check_in_datetime': False,
                'check_out_datetime': False,
                'check_in_latitude': 0.0,
                'check_in_longitude': 0.0,
                'check_out_latitude': 0.0,
                'check_out_longitude': 0.0,
            })
