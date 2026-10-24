# Part of the Van Sales project.

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class FleetVehicle(models.Model):
    """Van sales extension of the standard fleet vehicle.

    A sales van is a ``fleet.vehicle`` with two things added: the salesman who
    drives it and the stock location it carries. Nothing else - routes, plans
    and orders point at the van, not the other way round.

    The salesman is a ``res.users``, not Fleet's own ``driver_id``:
    ``driver_id`` points at ``res.partner`` and therefore cannot scope access,
    record rules or documents.
    """

    _inherit = 'fleet.vehicle'

    # Technical flag, never shown on a form. It is what separates sales vans
    # from the company's other Fleet vehicles: the Sales Van menu filters on it
    # and sets it on every vehicle created there.
    is_sales_van = fields.Boolean(
        string="Sales Van", default=False, copy=False)
    salesman_user_id = fields.Many2one(
        comodel_name='res.users',
        string="Van Salesman",
        domain="[('share', '=', False)]",
        copy=False,
        tracking=True,
        index='btree_not_null',
        help="The salesman operating this van. His sale orders ship from this "
             "van's stock and land on his daily visit plan.")
    van_location_id = fields.Many2one(
        comodel_name='stock.location',
        string="Van Stock Location",
        domain="[('usage', '=', 'internal')]",
        copy=False,
        tracking=True,
        index='btree_not_null',
        help="Internal stock location holding this van's stock. Created "
             "automatically when the van is saved.")

    # A stock location can back at most one active sales van. A partial unique
    # index, so it also holds against concurrent writes and direct SQL.
    _van_location_uniq = models.UniqueIndex(
        "(van_location_id) WHERE van_location_id IS NOT NULL"
        " AND is_sales_van IS TRUE AND active IS TRUE",
        "This stock location is already used by another active sales van. "
        "Each van needs its own location, otherwise their stock cannot be "
        "told apart.",
    )

    # --------------------------------------------------------------------
    # Warehouse
    # --------------------------------------------------------------------
    def _van_sales_resolve_warehouse(self, warehouse=False):
        """The warehouse this van belongs to.

        Not stored on the van: the van's stock location already lives under a
        warehouse, and ``stock.location.warehouse_id`` says which. Before the
        location exists (at creation), the company's first warehouse is used.
        """
        self.ensure_one()
        if warehouse:
            return warehouse
        if self.van_location_id.warehouse_id:
            return self.van_location_id.warehouse_id
        company = self.company_id or self.env.company
        return self.env['stock.warehouse'].search(
            [('company_id', '=', company.id)], limit=1)

    # --------------------------------------------------------------------
    # Van stock location provisioning
    # --------------------------------------------------------------------
    def _van_sales_fallback_location_name(self):
        """Name used when the vehicle has no plate yet."""
        self.ensure_one()
        return "Van %s" % self.id

    def _van_sales_location_name(self, parent):
        """Plate number, made unique among its siblings.

        The vehicle's ``name`` is deliberately not used: it is
        "Brand/Model/Plate", and the slashes would read as location levels in
        ``complete_name``.
        """
        self.ensure_one()
        name = (self.license_plate or "").strip() \
            or self._van_sales_fallback_location_name()
        clash = self.env['stock.location'].sudo().with_context(
            active_test=False).search_count([
                ('location_id', '=', parent.id),
                ('name', '=', name),
            ])
        if clash:
            name = "%s (%s)" % (name, self.id)
        return name

    def _van_sales_provision_location(self, warehouse=False):
        """Create and assign this van's stock location.

        Idempotent: a van that already has a location is returned untouched.
        Returns an empty recordset when no warehouse can be resolved, so the
        caller degrades to the manual path rather than failing.
        """
        self.ensure_one()
        if self.van_location_id:
            return self.van_location_id
        warehouse = self._van_sales_resolve_warehouse(warehouse)
        if not warehouse:
            return self.env['stock.location']
        parent = self.env['stock.location']._van_sales_vans_parent(warehouse)
        if not parent:
            return self.env['stock.location']
        # sudo: see stock.location._van_sales_vans_parent.
        location = self.env['stock.location'].sudo().create({
            'name': self._van_sales_location_name(parent),
            'usage': 'internal',
            'location_id': parent.id,
            'company_id': (self.company_id or warehouse.company_id).id,
        })
        self.with_context(van_sales_no_autoprovision=True).write({
            'van_location_id': location.id,
            'is_sales_van': True,
        })
        self.message_post(body=_(
            "Van stock location %s created.", location.display_name))
        return location

    def _van_sales_autoprovision(self):
        """Provision every sales van in self that still lacks a location."""
        if self.env.context.get('van_sales_no_autoprovision'):
            return
        for vehicle in self.filtered(
                lambda v: v.is_sales_van and not v.van_location_id):
            vehicle._van_sales_provision_location()

    def _van_sales_sync_location_name(self):
        """Rename a location that was auto-named before the plate was known.

        Strictly narrow on purpose: it fires only when the location still
        carries the exact fallback name this module generated. A location the
        user renamed themselves is never touched.
        """
        for vehicle in self:
            location = vehicle.van_location_id
            if not location or not (vehicle.license_plate or "").strip():
                continue
            if location.name != vehicle._van_sales_fallback_location_name():
                continue
            new_name = vehicle._van_sales_location_name(location.location_id)
            if new_name != location.name:
                location.sudo().write({'name': new_name})
                vehicle.message_post(body=_(
                    "Van stock location renamed to %s.", new_name))

    # --------------------------------------------------------------------
    # ORM overrides
    # --------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        vehicles = super().create(vals_list)
        vehicles._van_sales_autoprovision()
        return vehicles

    def write(self, vals):
        result = super().write(vals)
        if vals.get('is_sales_van'):
            self._van_sales_autoprovision()
        if 'license_plate' in vals:
            self._van_sales_sync_location_name()
        return result

    # --------------------------------------------------------------------
    # Constraints
    # --------------------------------------------------------------------
    @api.constrains('van_location_id')
    def _check_van_location_usage(self):
        for vehicle in self:
            location = vehicle.van_location_id
            if location and location.usage != 'internal':
                raise ValidationError(_(
                    "The van stock location of %(vehicle)s must be an internal "
                    "location, but %(location)s is of type '%(usage)s'. Only "
                    "internal locations hold and value stock.",
                    vehicle=vehicle.display_name,
                    location=location.display_name,
                    usage=location.usage,
                ))

    @api.constrains('company_id', 'van_location_id', 'salesman_user_id')
    def _check_van_company(self):
        """Company consistency of the two fields this module adds.

        ``fleet.vehicle`` does not set ``_check_company_auto``, and turning it
        on here would change behaviour for every existing fleet field. A
        vehicle with no company is shared and passes.
        """
        for vehicle in self:
            company = vehicle.company_id
            if not company:
                continue
            for field_name, label in (
                ('van_location_id', _("van stock location")),
                ('salesman_user_id', _("van salesman")),
            ):
                record = vehicle[field_name]
                if record and record.company_id and record.company_id != company:
                    raise ValidationError(_(
                        "The %(label)s of %(vehicle)s belongs to company "
                        "%(other)s but the vehicle belongs to %(company)s.",
                        label=label,
                        vehicle=vehicle.display_name,
                        other=record.company_id.display_name,
                        company=company.display_name,
                    ))

    @api.constrains('is_sales_van', 'salesman_user_id', 'active')
    def _check_salesman_single_van(self):
        """One salesman drives one van at a time.

        The whole flow depends on it: a salesman's sale order finds its van -
        and therefore its stock location - through this link, so two vans per
        salesman would make that lookup ambiguous.
        """
        for vehicle in self:
            if not (vehicle.is_sales_van and vehicle.salesman_user_id
                    and vehicle.active):
                continue
            # sudo: this is an integrity check, and a record rule could
            # otherwise hide the conflicting van from the current user.
            conflict = self.sudo().search([
                ('id', '!=', vehicle.id),
                ('is_sales_van', '=', True),
                ('salesman_user_id', '=', vehicle.salesman_user_id.id),
            ], limit=1)
            if conflict:
                raise ValidationError(_(
                    "%(salesman)s is already assigned to van %(other)s. A "
                    "salesman can operate only one van at a time, otherwise "
                    "van stock and sales cannot be attributed to them.",
                    salesman=vehicle.salesman_user_id.display_name,
                    other=conflict.display_name,
                ))

    # --------------------------------------------------------------------
    # Lookup
    # --------------------------------------------------------------------
    @api.model
    def _van_sales_van_of(self, user):
        """The active sales van driven by ``user``, or an empty recordset.

        sudo: used by server-side hooks where the acting user may not be able
        to read Fleet. Returns at most one van - guaranteed by
        ``_check_salesman_single_van``.
        """
        if not user:
            return self.browse()
        return self.sudo().search([
            ('is_sales_van', '=', True),
            ('salesman_user_id', '=', user.id),
        ], limit=1)

    # --------------------------------------------------------------------
    # Actions
    # --------------------------------------------------------------------
    def action_van_sales_create_location(self):
        """Open the provisioning wizard for the selected vehicles."""
        return {
            'type': 'ir.actions.act_window',
            'name': _("Create Van Stock Locations"),
            'res_model': 'van.sales.van.location.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_vehicle_ids': self.ids,
                'active_model': 'fleet.vehicle',
                'active_ids': self.ids,
            },
        }

    def action_van_sales_view_quants(self):
        """Show what is currently on the van."""
        self.ensure_one()
        if not self.van_location_id:
            raise UserError(_(
                "%s has no van stock location yet.", self.display_name))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Van Stock"),
            'res_model': 'stock.quant',
            'view_mode': 'list,form',
            'domain': [('location_id', 'child_of', self.van_location_id.id)],
            'context': {'search_default_internal_loc': 1},
        }
