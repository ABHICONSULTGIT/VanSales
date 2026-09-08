# Part of the Van Sales project.
"""Transactional records a van pulls down.

Scoped twice over: to the device's own van, and to a recent window. A van does
not need last year's visits on the handset, and pulling them would make every
sync slower for no benefit.
"""

from odoo import api, fields, models

PARAM_HISTORY_DAYS = 'van_sales.sync_history_days'
DEFAULT_HISTORY_DAYS = 7


def _history_cutoff(env):
    try:
        days = max(int(env['ir.config_parameter'].sudo().get_param(
            PARAM_HISTORY_DAYS, DEFAULT_HISTORY_DAYS)), 1)
    except (TypeError, ValueError):
        days = DEFAULT_HISTORY_DAYS
    return fields.Date.subtract(fields.Date.context_today(env['res.users']), days=days)


def _ids(data, model):
    return [row['id'] for row in data.get(model, [])]


class VanSalesVisitPlan(models.Model):
    _name = 'van.sales.visit.plan'
    _inherit = ['van.sales.visit.plan', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        if not device.van_id:
            return False
        return [
            ('van_id', '=', device.van_id.id),
            ('date', '>=', _history_cutoff(self.env)),
        ]

    @api.model
    def _van_load_fields(self, device):
        return ['name', 'date', 'route_id', 'van_id', 'salesman_user_id',
                'state', 'company_id']

    @api.model
    def _van_load_order(self, device):
        return 'date desc, id desc'


class VanSalesVisit(models.Model):
    _name = 'van.sales.visit'
    _inherit = ['van.sales.visit', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        plan_ids = _ids(data, 'van.sales.visit.plan')
        return [('plan_id', 'in', plan_ids)] if plan_ids else False

    @api.model
    def _van_load_fields(self, device):
        return ['name', 'plan_id', 'sequence', 'stop_type', 'partner_id',
                'stop_location_id', 'date', 'route_id', 'van_id', 'state',
                'is_adhoc', 'adhoc_reason', 'skip_reason',
                'check_in_datetime', 'check_out_datetime',
                'check_in_latitude', 'check_in_longitude',
                'check_out_latitude', 'check_out_longitude',
                'duration_minutes', 'van_client_uuid', 'company_id']

    @api.model
    def _van_load_order(self, device):
        return 'plan_id, sequence, id'


class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        """Open customer invoices for the customers being sent.

        Only unpaid ones: the app needs them to collect against, and shipping
        a customer's whole invoice history down a mobile connection buys
        nothing.
        """
        partner_ids = _ids(data, 'res.partner')
        if not partner_ids:
            return False
        return [
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('company_id', '=', device.company_id.id),
            ('partner_id', 'in', partner_ids),
        ]

    @api.model
    def _van_load_fields(self, device):
        return ['name', 'partner_id', 'invoice_date', 'invoice_date_due',
                'amount_total', 'amount_residual', 'currency_id',
                'payment_state', 'state', 'van_id', 'van_visit_id',
                'van_client_uuid', 'company_id']

    @api.model
    def _van_load_order(self, device):
        return 'invoice_date_due, id'


class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        if not device.van_id:
            return False
        return [
            ('van_id', '=', device.van_id.id),
            ('date_order', '>=', _history_cutoff(self.env)),
        ]

    @api.model
    def _van_load_fields(self, device):
        return ['name', 'partner_id', 'date_order', 'state', 'amount_total',
                'amount_untaxed', 'amount_tax', 'currency_id', 'van_id',
                'van_route_id', 'van_visit_id', 'van_client_uuid',
                'invoice_status', 'delivery_status', 'company_id']

    @api.model
    def _van_load_order(self, device):
        return 'date_order desc, id desc'


class SaleOrderLine(models.Model):
    _name = 'sale.order.line'
    _inherit = ['sale.order.line', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        order_ids = _ids(data, 'sale.order')
        return [('order_id', 'in', order_ids)] if order_ids else False

    @api.model
    def _van_load_fields(self, device):
        return ['order_id', 'sequence', 'product_id', 'name',
                'product_uom_qty', 'product_uom_id', 'price_unit',
                'discount', 'tax_ids', 'price_subtotal', 'price_total',
                'qty_delivered', 'qty_invoiced', 'display_type']

    @api.model
    def _van_load_order(self, device):
        return 'order_id, sequence, id'


class VanSalesCollection(models.Model):
    _name = 'van.sales.collection'
    _inherit = ['van.sales.collection', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        if not device.van_id:
            return False
        return [
            ('van_id', '=', device.van_id.id),
            ('date', '>=', _history_cutoff(self.env)),
        ]

    @api.model
    def _van_load_fields(self, device):
        return ['name', 'partner_id', 'van_id', 'visit_id', 'journal_id',
                'date', 'amount_total', 'currency_id', 'state',
                'van_client_uuid', 'company_id']

    @api.model
    def _van_load_order(self, device):
        return 'date desc, id desc'


class VanSalesCollectionLine(models.Model):
    _name = 'van.sales.collection.line'
    _inherit = ['van.sales.collection.line', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        collection_ids = _ids(data, 'van.sales.collection')
        return [('collection_id', 'in', collection_ids)] if collection_ids else False

    @api.model
    def _van_load_fields(self, device):
        return ['collection_id', 'move_id', 'amount', 'payment_id',
                'currency_id']


class StockPicking(models.Model):
    _name = 'stock.picking'
    _inherit = ['stock.picking', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        """Van loads and returns waiting for this van, plus recent history."""
        if not device.van_id:
            return False
        return [
            ('van_id', '=', device.van_id.id),
            ('van_operation', 'in', ('load', 'unload', 'van_transfer')),
            '|',
            ('state', 'not in', ('done', 'cancel')),
            ('scheduled_date', '>=', _history_cutoff(self.env)),
        ]

    @api.model
    def _van_load_fields(self, device):
        return ['name', 'origin', 'state', 'scheduled_date', 'date_done',
                'location_id', 'location_dest_id', 'van_id', 'van_operation',
                'van_discrepancy_note', 'company_id']

    @api.model
    def _van_load_order(self, device):
        return 'scheduled_date desc, id desc'


class StockMove(models.Model):
    _name = 'stock.move'
    _inherit = ['stock.move', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        picking_ids = _ids(data, 'stock.picking')
        return [('picking_id', 'in', picking_ids)] if picking_ids else False

    @api.model
    def _van_load_fields(self, device):
        return ['picking_id', 'product_id', 'product_uom_qty', 'quantity',
                'product_uom', 'state', 'picked']

    @api.model
    def _van_load_order(self, device):
        return 'picking_id, sequence, id'
