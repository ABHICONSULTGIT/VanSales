# Part of the Van Sales project.

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    van_picking_ids = fields.One2many(
        comodel_name='stock.picking', inverse_name='van_id',
        string="Van Transfers")
    van_pending_picking_count = fields.Integer(
        string="Pending Transfers", compute='_compute_van_picking_counts')
    van_picking_count = fields.Integer(
        string="Transfers", compute='_compute_van_picking_counts')
    van_reconciliation_count = fields.Integer(
        string="Reconciliations", compute='_compute_van_reconciliation_count')

    # --------------------------------------------------------------------
    # Compute
    # --------------------------------------------------------------------
    def _compute_van_picking_counts(self):
        totals, pending = {}, {}
        if self.ids:
            for van, count in self.env['stock.picking']._read_group(
                    [('van_id', 'in', self.ids)], ['van_id'], ['__count']):
                totals[van.id] = count
            for van, count in self.env['stock.picking']._read_group(
                    [('van_id', 'in', self.ids),
                     ('state', 'not in', ('done', 'cancel'))],
                    ['van_id'], ['__count']):
                pending[van.id] = count
        for vehicle in self:
            vehicle.van_picking_count = totals.get(vehicle.id, 0)
            vehicle.van_pending_picking_count = pending.get(vehicle.id, 0)

    def _compute_van_reconciliation_count(self):
        counts = {}
        if self.ids:
            for van, count in self.env['van.sales.reconciliation']._read_group(
                    [('van_id', 'in', self.ids)], ['van_id'], ['__count']):
                counts[van.id] = count
        for vehicle in self:
            vehicle.van_reconciliation_count = counts.get(vehicle.id, 0)

    # --------------------------------------------------------------------
    # Stock service - consumed by the sales module later
    # --------------------------------------------------------------------
    def _van_sales_available_quantities(self, products=None):
        """On-hand quantity per product in this van's location.

        Returned in each product's own unit of measure, because
        ``stock.quant.quantity`` is stored in the product UoM.

        sudo: a salesman has read access to their own van's stock through the
        quant ACL, but this helper is also called from server-side checks where
        the acting user may differ. The result is scoped to one van location,
        so nothing outside that van is exposed.

        :return: ``{product_id: float}``, missing products meaning zero.
        """
        self.ensure_one()
        if not self.van_location_id:
            return {}
        domain = [('location_id', 'child_of', self.van_location_id.id)]
        if products is not None:
            if not products:
                return {}
            domain.append(('product_id', 'in', products.ids))
        return {
            product.id: quantity
            for product, quantity in self.env['stock.quant'].sudo()._read_group(
                domain, ['product_id'], ['quantity:sum'])
        }

    def _van_sales_check_quantity(self, product, quantity, uom=None):
        """Verdict on selling ``quantity`` of ``product`` from this van.

        Odoo 19 has no negative-stock setting anywhere - there is no
        ``allow_negative_stock`` field on the product, the category, the
        location or the company - so this is the only control over selling more
        than the van carries. The policy comes from the product, falling back
        to its category.

        :return: dict with
                 ``ok`` - True when the van carries enough;
                 ``policy`` - 'allow' / 'warn' / 'block', meaningful only when
                 ``ok`` is False;
                 ``available`` and ``shortage`` in the product's UoM.
        """
        self.ensure_one()
        product_uom = product.uom_id
        needed = (uom._compute_quantity(quantity, product_uom, round=False)
                  if uom and uom != product_uom else quantity)
        available = self._van_sales_available_quantities(product).get(
            product.id, 0.0)
        shortage = needed - available
        if product_uom.compare(shortage, 0.0) <= 0:
            return {'ok': True, 'policy': 'allow',
                    'available': available, 'shortage': 0.0}
        return {
            'ok': False,
            'policy': product.van_sale_stock_policy_effective or 'warn',
            'available': available,
            'shortage': shortage,
        }

    # --------------------------------------------------------------------
    # Actions
    # --------------------------------------------------------------------
    def _van_sales_internal_picking_type(self):
        """The warehouse's internal operation type, with a clear failure."""
        self.ensure_one()
        warehouse = self.van_warehouse_id or self.env['stock.warehouse'].search(
            [('company_id', '=', (self.company_id or self.env.company).id)],
            limit=1)
        if not warehouse:
            raise UserError(_(
                "No warehouse is set on van %s and none could be found for "
                "its company.", self.display_name))
        picking_type = warehouse.with_context(active_test=False).int_type_id
        if not picking_type:
            raise UserError(_(
                "Warehouse %s has no internal operation type.",
                warehouse.display_name))
        if not picking_type.active:
            raise UserError(_(
                "The internal operation type of warehouse %s is archived. "
                "Enable Storage Locations in Inventory settings, or reinstall "
                "Van Sales - Stock, which turns it on.",
                warehouse.display_name))
        return warehouse, picking_type

    def _van_sales_check_ready(self):
        self.ensure_one()
        if not self.is_sales_van:
            raise UserError(_(
                "%s is not marked as a sales van.", self.display_name))
        if not self.van_location_id:
            raise UserError(_(
                "%s has no van stock location yet.", self.display_name))

    def action_van_sales_load(self):
        """Open a new internal transfer from the warehouse into this van."""
        self.ensure_one()
        self._van_sales_check_ready()
        warehouse, picking_type = self._van_sales_internal_picking_type()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Load Van"),
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'context': {
                'default_picking_type_id': picking_type.id,
                'default_location_id': warehouse.lot_stock_id.id,
                'default_location_dest_id': self.van_location_id.id,
                'default_origin': _("Load %s", self.display_name),
            },
        }

    def action_van_sales_unload(self):
        """Open a new internal transfer returning stock to the warehouse."""
        self.ensure_one()
        self._van_sales_check_ready()
        warehouse, picking_type = self._van_sales_internal_picking_type()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Return Van Stock"),
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'context': {
                'default_picking_type_id': picking_type.id,
                'default_location_id': self.van_location_id.id,
                'default_location_dest_id': warehouse.lot_stock_id.id,
                'default_origin': _("Return from %s", self.display_name),
            },
        }

    def action_van_sales_view_pickings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Van Transfers"),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('van_id', '=', self.id)],
            'context': {'default_van_id': self.id},
        }

    def action_van_sales_view_reconciliations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Van Reconciliations"),
            'res_model': 'van.sales.reconciliation',
            'view_mode': 'list,form',
            'domain': [('van_id', '=', self.id)],
            'context': {'default_van_id': self.id},
        }

    def action_van_sales_new_reconciliation(self):
        """Start today's reconciliation for this van, stops pre-loaded."""
        self.ensure_one()
        self._van_sales_check_ready()
        reconciliation = self.env['van.sales.reconciliation'].create({
            'van_id': self.id,
        })
        reconciliation.action_generate_lines()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Van Reconciliation"),
            'res_model': 'van.sales.reconciliation',
            'view_mode': 'form',
            'res_id': reconciliation.id,
        }
