# Part of the Van Sales project.

from odoo import _, api, fields, models
from odoo.exceptions import UserError

VAN_DELIVERY_SEQUENCE_CODE = 'VOUT'


class FleetVehicle(models.Model):
    """Gives each sales van a delivery route that ships from its own stock.

    This is the crux of selling from a van. A sale order's delivery takes its
    source location from the ``stock.rule`` that procurement matches - read off
    ``rule.location_src_id`` and nowhere else. There is no values key anywhere
    in ``stock``, ``sale`` or ``sale_stock`` that lets a caller override it.

    So the van gets its own route, whose single pull rule sources from the van's
    stock location. Odoo's own procurement then does everything else, and
    quantity delivered, invoice status, backorders and returns all behave
    exactly as standard.

    A route and a rule per van, not a warehouse per van: a warehouse creates
    eight operation types and eight sequences each, and the operation type is
    shared here - one per warehouse, not one per van.
    """

    _inherit = 'fleet.vehicle'

    van_delivery_route_id = fields.Many2one(
        comodel_name='stock.route', string="Van Delivery Route",
        readonly=True, copy=False, index='btree_not_null',
        help="Route whose rule ships this van's sales out of its own stock "
             "location instead of the warehouse.")
    van_sale_order_ids = fields.One2many(
        comodel_name='sale.order', inverse_name='van_id', string="Van Orders")
    van_sale_order_count = fields.Integer(
        string="Orders", compute='_compute_van_sale_order_count')

    def _compute_van_sale_order_count(self):
        counts = {}
        if self.ids:
            for van, count in self.env['sale.order']._read_group(
                    [('van_id', 'in', self.ids)], ['van_id'], ['__count']):
                counts[van.id] = count
        for vehicle in self:
            vehicle.van_sale_order_count = counts.get(vehicle.id, 0)

    # --------------------------------------------------------------------
    # Provisioning
    # --------------------------------------------------------------------
    @api.model
    def _van_sales_customer_location(self):
        location = self.env.ref(
            'stock.stock_location_customers', raise_if_not_found=False)
        if not location:
            raise UserError(_(
                "The standard Customers location is missing, so van deliveries "
                "have nowhere to ship to."))
        return location

    def _van_sales_delivery_picking_type(self, warehouse):
        """One shared 'Van Sales Delivery' operation type per warehouse.

        Shared on purpose: the source location comes from the route's rule, not
        from the operation type, so one type serves every van. Odoo builds its
        sequence automatically from ``sequence_code``.
        """
        self.ensure_one()
        Type = self.env['stock.picking.type'].sudo()
        picking_type = Type.with_context(active_test=False).search([
            ('warehouse_id', '=', warehouse.id),
            ('code', '=', 'outgoing'),
            ('sequence_code', '=', VAN_DELIVERY_SEQUENCE_CODE),
        ], limit=1)
        if picking_type:
            if not picking_type.active:
                picking_type.active = True
            return picking_type
        return Type.create({
            'name': _("Van Sales Delivery"),
            'code': 'outgoing',
            'sequence_code': VAN_DELIVERY_SEQUENCE_CODE,
            'warehouse_id': warehouse.id,
            'company_id': warehouse.company_id.id,
            'default_location_src_id': warehouse.lot_stock_id.id,
            'default_location_dest_id': self._van_sales_customer_location().id,
        })

    def _van_sales_provision_delivery_route(self):
        """Create and assign this van's delivery route. Idempotent."""
        self.ensure_one()
        if self.van_delivery_route_id:
            return self.van_delivery_route_id
        if not (self.is_sales_van and self.van_location_id):
            return self.env['stock.route']
        warehouse = self._van_sales_resolve_warehouse()
        if not warehouse:
            return self.env['stock.route']
        picking_type = self._van_sales_delivery_picking_type(warehouse)
        company = self.company_id or warehouse.company_id
        # sudo: routes and rules are Inventory Administrator records, and a van
        # is registered by a Van Sales Administrator. Tightly bounded - one
        # route, one rule, sourced from this van's own location.
        route = self.env['stock.route'].sudo().create({
            'name': _("Van Delivery: %s", self.display_name),
            'company_id': company.id,
            # Low sequence so this rule outranks the warehouse's own delivery
            # rule when procurement chooses between them.
            'sequence': 5,
            'product_selectable': False,
            'product_categ_selectable': False,
            'warehouse_selectable': False,
            'sale_selectable': True,
            'rule_ids': [(0, 0, {
                'name': _("Deliver from %s", self.van_location_id.name),
                'action': 'pull',
                'location_src_id': self.van_location_id.id,
                'location_dest_id': self._van_sales_customer_location().id,
                'picking_type_id': picking_type.id,
                'warehouse_id': warehouse.id,
                'procure_method': 'make_to_stock',
                'company_id': company.id,
            })],
        })
        self.with_context(van_sales_no_route_provision=True).write(
            {'van_delivery_route_id': route.id})
        self.message_post(body=_(
            "Van delivery route %s created. Sales from this van now ship out "
            "of its own stock location.", route.display_name))
        return route

    def _van_sales_autoprovision_route(self):
        if self.env.context.get('van_sales_no_route_provision'):
            return
        for vehicle in self.filtered(
                lambda v: v.is_sales_van and v.van_location_id
                and not v.van_delivery_route_id):
            vehicle._van_sales_provision_delivery_route()

    # --------------------------------------------------------------------
    # ORM
    # --------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        # van_sales_base provisions the stock location inside super(), so by
        # the time we get here the location the route needs already exists.
        vehicles = super().create(vals_list)
        vehicles._van_sales_autoprovision_route()
        return vehicles

    def write(self, vals):
        result = super().write(vals)
        if vals.get('is_sales_van') or 'van_location_id' in vals:
            self._van_sales_autoprovision_route()
        return result

    # --------------------------------------------------------------------
    # Actions
    # --------------------------------------------------------------------
    def action_van_sales_view_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Van Orders"),
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('van_id', '=', self.id)],
            'context': {'default_van_id': self.id},
        }
