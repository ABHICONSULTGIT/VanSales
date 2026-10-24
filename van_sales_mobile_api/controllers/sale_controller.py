# Part of the Van Sales project.

from odoo import Command, fields, http
from odoo.http import request
from odoo.tools import html2plaintext

from .base import (
    API_PREFIX, ApiError, as_int, body, date_param, datetime_domain,
    fmt_datetime, get_own, lines_payload, me, money, my_van, ok, paginate,
    param, ref, token_required,
)
from .invoice_controller import invoice_detail

STATE_FILTERS = {
    'quotation': [('state', 'in', ('draft', 'sent'))],
    'confirmed': [('state', '=', 'sale')],
    'cancelled': [('state', '=', 'cancel')],
}


def delivery_status(order):
    pickings = order.picking_ids.filtered(lambda p: p.state != 'cancel')
    if not pickings:
        return None
    if all(p.state == 'done' for p in pickings):
        return 'full'
    if any(p.state == 'done' for p in pickings):
        return 'partial'
    return 'pending'


def order_list_item(order):
    return {
        'id': order.id,
        'name': order.name,
        'date': fmt_datetime(order.date_order),
        'customer': ref(order.partner_id),
        'state': order.state,
        'amount': money(order.amount_total, order.currency_id),
        'invoice_status': order.invoice_status or None,
    }


def order_detail(order, warnings=None):
    currency = order.currency_id
    return {
        'id': order.id,
        'name': order.name,
        'date': fmt_datetime(order.date_order),
        'state': order.state,
        'customer': ref(order.partner_id),
        'visit_id': order.van_visit_id.id or None,
        'note': html2plaintext(order.note).strip() or None if order.note else None,
        'lines': [{
            'id': line.id,
            'product_id': line.product_id.id,
            'product': line.product_id.name,
            'qty': line.product_uom_qty,
            'delivered_qty': line.qty_delivered,
            'price_unit': money(line.price_unit, currency),
            'discount': line.discount,
            'subtotal': money(line.price_subtotal, currency),
        } for line in order.order_line.filtered(lambda l: not l.display_type)],
        'untaxed': money(order.amount_untaxed, currency),
        'tax': money(order.amount_tax, currency),
        'total': money(order.amount_total, currency),
        'currency': currency.name,
        'delivery_status': delivery_status(order),
        'invoice_status': order.invoice_status or None,
        # sudo: the office may have invoiced his order under another
        # salesperson; he still needs to see that it is invoiced.
        'invoices': [{
            'id': inv.id, 'name': inv.name, 'state': inv.state,
            'payment_state': inv.payment_state,
        } for inv in order.sudo().invoice_ids],
        'warnings': warnings or [],
    }


def get_order(order_id):
    return get_own('sale.order', order_id, [('user_id', '=', me().id)])


def order_lines_commands(data):
    commands = []
    for product, qty in lines_payload(data):
        if not product.sale_ok:
            raise ApiError("%s cannot be sold." % product.display_name)
        commands.append(Command.create({
            'product_id': product.id, 'product_uom_qty': qty}))
    return commands


def stock_warnings(order):
    """Shortages that a 'warn' over-sell policy will let through.

    Worked out before confirming: the backend records them in the chatter,
    and the app needs them as a list it can show.
    """
    van = order.van_id
    if not van or not van.van_location_id:
        return []
    available = van._van_sales_available_quantities()
    warnings = []
    for product, needed in order._van_sales_required_quantities().items():
        on_van = available.get(product.id, 0.0)
        if product.uom_id.compare(needed, on_van) > 0 and \
                (product.van_sale_stock_policy_effective or 'warn') == 'warn':
            warnings.append(
                "%s: %s needed, %s on the van" % (product.display_name,
                                                   needed, on_van))
    return warnings


class VanSalesOrderController(http.Controller):

    @http.route(API_PREFIX + '/orders', type='http', auth='public',
                methods=['GET'], csrf=False, cors='*')
    @token_required
    def list(self, **kw):
        domain = [('user_id', '=', me().id)]
        state = param('state')
        if state:
            if state not in STATE_FILTERS:
                raise ApiError("'state' must be one of: %s."
                               % ", ".join(STATE_FILTERS))
            domain += STATE_FILTERS[state]
        customer_id = param('customer_id')
        if customer_id:
            partner = request.env['res.partner'].browse(
                as_int(customer_id, 'customer_id')).commercial_partner_id
            domain.append(('partner_id', 'child_of', partner.id))
        domain += datetime_domain('date_order', date_param('date_from'),
                                  date_param('date_to'))
        orders, page = paginate(request.env['sale.order'], domain,
                                order='date_order desc, id desc')
        return ok([order_list_item(o) for o in orders], pagination=page)

    @http.route(API_PREFIX + '/orders/<int:order_id>', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    @token_required
    def detail(self, order_id, **kw):
        return ok(order_detail(get_order(order_id)))

    @http.route(API_PREFIX + '/orders', type='http', auth='public',
                methods=['POST'], csrf=False, cors='*')
    @token_required
    def create(self, **kw):
        data = body()
        van = my_van()
        Order = request.env['sale.order']

        client_uuid = (data.get('client_uuid') or '').strip() or False
        if client_uuid:
            existing = Order.search([('van_client_uuid', '=', client_uuid)],
                                    limit=1)
            if existing:
                if existing.user_id != me():
                    raise ApiError("This client_uuid is already used.", 409)
                return ok(order_detail(existing), "Order already received.")

        partner = request.env['res.partner'].search(
            [('id', '=', as_int(data.get('customer_id'), 'customer_id'))],
            limit=1)
        if not partner:
            raise ApiError("Customer not found.", 404)

        values = {
            'partner_id': partner.id,
            # Set explicitly: Odoo would otherwise take the customer's own
            # salesperson, and the order would land on someone else's plan.
            'user_id': me().id,
            'van_id': van.id,
            'order_line': order_lines_commands(data),
            'van_client_uuid': client_uuid,
            'van_captured_datetime': fields.Datetime.now(),
        }
        if data.get('note'):
            values['note'] = str(data['note'])

        visit_id = data.get('visit_id')
        if visit_id:
            visit = get_own('van.sales.visit', visit_id,
                            [('salesman_user_id', '=', me().id)])
            if visit.sale_order_id:
                # sudo: the order may be one the office keyed for this stop.
                raise ApiError("This stop already has the order %s."
                               % visit.sale_order_id.sudo().name, 409)
            if visit.partner_id and visit.partner_id.commercial_partner_id \
                    != partner.commercial_partner_id:
                raise ApiError("This stop is for %s, not %s."
                               % (visit.partner_id.display_name,
                                  partner.display_name))
            if visit.date != fields.Date.context_today(me()):
                raise ApiError("Orders can only be taken on today's plan.", 409)
            values.update({'van_visit_id': visit.id,
                           'van_route_id': visit.plan_id.route_id.id})

        # Without a visit, the sale order hook puts the order on today's plan:
        # the customer's route stop if there is one, else a new line.
        order = Order.create(values)
        return ok(order_detail(order), "Order created.", status=201)

    @http.route(API_PREFIX + '/orders/<int:order_id>', type='http',
                auth='public', methods=['PUT'], csrf=False, cors='*')
    @token_required
    def update(self, order_id, **kw):
        order = get_order(order_id)
        if order.state not in ('draft', 'sent'):
            raise ApiError("Only a quotation can be changed.", 409)
        data = body()
        values = {}
        if 'lines' in data:
            values['order_line'] = [Command.clear()] + order_lines_commands(data)
        if 'note' in data:
            values['note'] = str(data['note'] or '') or False
        if not values:
            raise ApiError("Nothing to update.")
        order.write(values)
        return ok(order_detail(order), "Order updated.")

    @http.route(API_PREFIX + '/orders/<int:order_id>/confirm', type='http',
                auth='public', methods=['POST'], csrf=False, cors='*')
    @token_required
    def confirm(self, order_id, **kw):
        order = get_order(order_id)
        if order.state not in ('draft', 'sent'):
            raise ApiError("Only a quotation can be confirmed.", 409)
        if not order.order_line.filtered(lambda l: not l.display_type):
            raise ApiError("The order has no lines.")
        warnings = stock_warnings(order)
        # Runs the van stock policy and the credit policy; a 'block' policy
        # raises and the request is rolled back.
        order.action_confirm()
        if order.van_credit_warning:
            warnings.append(order.van_credit_warning)
        return ok(order_detail(order, warnings), "Order confirmed.")

    @http.route(API_PREFIX + '/orders/<int:order_id>/deliver', type='http',
                auth='public', methods=['POST'], csrf=False, cors='*')
    @token_required
    def deliver(self, order_id, **kw):
        order = get_order(order_id)
        if order.state != 'sale':
            raise ApiError("Confirm the order before delivering it.", 409)
        pickings = order.picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel')
            and p.picking_type_code == 'outgoing')
        if not pickings:
            raise ApiError("Nothing is left to deliver on this order.", 409)
        for picking in pickings:
            for move in picking.move_ids.filtered(
                    lambda m: m.state not in ('done', 'cancel')):
                move.quantity = move.product_uom_qty
                move.picked = True
            result = picking.with_context(skip_sms=True).button_validate()
            if result is not True:
                raise ApiError("Delivery %s needs to be completed in the "
                               "backend." % picking.name, 409)
        return ok(order_detail(order), "Order delivered.")

    @http.route(API_PREFIX + '/orders/<int:order_id>/invoice', type='http',
                auth='public', methods=['POST'], csrf=False, cors='*')
    @token_required
    def invoice(self, order_id, **kw):
        order = get_order(order_id)
        data = body()
        client_uuid = (data.get('client_uuid') or '').strip() or False
        Move = request.env['account.move']
        if client_uuid:
            existing = Move.search([('van_client_uuid', '=', client_uuid)],
                                   limit=1)
            if existing:
                return ok(invoice_detail(existing), "Invoice already issued.")
        if order.state != 'sale':
            raise ApiError("Confirm the order before invoicing it.", 409)
        if order.invoice_status != 'to invoice':
            raise ApiError(
                "Nothing to invoice on this order. If its products are "
                "invoiced on delivery, deliver it first." if
                order.invoice_status == 'no' else
                "This order is already invoiced.", 409)
        # Odoo creates the invoice as sudo itself. Decision D2: post it too -
        # the salesman holds no Billing right. Bounded to this order of his,
        # just created, in this call.
        invoices = order._create_invoices()
        if client_uuid:
            invoices[:1].sudo().van_client_uuid = client_uuid
        invoices.sudo().action_post()
        invoice = Move.browse(invoices[:1].id)
        return ok(invoice_detail(invoice), "Invoice issued.", status=201)

    @http.route(API_PREFIX + '/orders/<int:order_id>/cancel', type='http',
                auth='public', methods=['POST'], csrf=False, cors='*')
    @token_required
    def cancel(self, order_id, **kw):
        order = get_order(order_id)
        if order.state == 'cancel':
            raise ApiError("The order is already cancelled.", 409)
        if any(p.state == 'done' for p in order.picking_ids):
            raise ApiError("A delivered order cannot be cancelled from the "
                           "app. Raise a return with the office.", 409)
        # sudo: an invoice the office raised under another salesperson.
        if any(inv.state == 'posted' for inv in order.sudo().invoice_ids):
            raise ApiError("An invoiced order cannot be cancelled from the "
                           "app. Ask the office for a credit note.", 409)
        order.action_cancel()
        return ok(order_detail(order), "Order cancelled.")
