# Part of the Van Sales project.

from odoo import _, api, fields, models


class VanSalesStopLocation(models.Model):
    """A place a van stops to sell, as opposed to a named customer.

    Confirmed with the client: some vans run a fixed round of known shops,
    others park at public places - a market, a labour camp, a busy junction -
    and sell to whoever walks up. A stop of the second kind is a *place*, and
    this is its master record.

    Deliberately a model of its own rather than a ``res.partner``. Reusing a
    partner would be tempting - an invoice needs one, and the address and geo
    fields come for free - but it would put places into the customer list and
    muddy every customer count and report. It also pre-empts a question that is
    still open: who the invoice is made out to on a walk-up sale. Keeping the
    place separate leaves that decision to ``van_sales_sale``; a link to a
    partner can be added here later if that is the answer.
    """

    _name = 'van.sales.stop.location'
    _inherit = ['mail.thread']
    _description = "Van Sales Stop Location"
    _order = 'name, id'

    name = fields.Char(
        string="Stop Name", required=True, tracking=True,
        help="How the salesman recognises the place, e.g. 'Industrial Area "
             "Labour Camp 3' or 'Friday Market - North Gate'.")
    code = fields.Char(
        string="Code", copy=False, tracking=True,
        help="Optional short code for reporting.")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        comodel_name='res.company', string="Company",
        required=True, index=True,
        default=lambda self: self.env.company)

    street = fields.Char(string="Address")
    city = fields.Char(string="City")
    latitude = fields.Float(string="Latitude", digits=(10, 7))
    longitude = fields.Float(string="Longitude", digits=(10, 7))
    note = fields.Text(string="Notes")

    route_line_ids = fields.One2many(
        comodel_name='van.sales.route.line', inverse_name='stop_location_id',
        string="On Routes")
    route_count = fields.Integer(
        string="Routes", compute='_compute_route_count')
    visit_count = fields.Integer(
        string="Visits", compute='_compute_visit_count')

    _code_company_uniq = models.UniqueIndex(
        "(code, company_id) WHERE code IS NOT NULL AND code != ''",
        "A stop location with this code already exists for this company.",
    )
    _latitude_range = models.Constraint(
        'CHECK(latitude >= -90 AND latitude <= 90)',
        "Latitude must be between -90 and 90 degrees.",
    )
    _longitude_range = models.Constraint(
        'CHECK(longitude >= -180 AND longitude <= 180)',
        "Longitude must be between -180 and 180 degrees.",
    )

    @api.depends('route_line_ids')
    def _compute_route_count(self):
        for location in self:
            location.route_count = len(location.route_line_ids)

    def _compute_visit_count(self):
        counts = dict(self.env['van.sales.visit']._read_group(
            [('stop_location_id', 'in', self.ids)],
            ['stop_location_id'], ['__count'],
        )) if self.ids else {}
        for location in self:
            location.visit_count = counts.get(location, 0)

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for location in self:
            location.display_name = (
                "[%s] %s" % (location.code, location.name)
                if location.code else (location.name or "")
            )

    def action_view_visits(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Visits"),
            'res_model': 'van.sales.visit',
            'view_mode': 'list,form',
            'domain': [('stop_location_id', '=', self.id)],
            'context': {'default_stop_location_id': self.id},
        }
