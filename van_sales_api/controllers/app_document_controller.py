# Part of the Van Sales project.
"""Orders, invoices, payments, GRNs, van stock, routes and notifications.

Read-only, in the mobile contract's shape. Every endpoint here is scoped to
the caller's own van; ``/stock/van/<vanId>`` additionally refuses a van id
that is not the caller's, rather than trusting the path.
"""

from odoo import fields, http
from odoo.http import request

from . import app_serializers as ser
from .base import ErrCode, get_query_bool, get_query_int, get_query_str, paginate
from .app_base import (app_error, app_partner_ids, app_response,
                       app_token_required, app_van, no_van_error)
from .app_master_controller import APP, _int_id


class VanSalesAppDocumentController(http.Controller):

    # =================================================================
    # ORDERS
    # =================================================================

    @http.route(APP + '/orders', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def orders(self, **kw):
        van = app_van()
        if not van:
            return no_van_error()
        domain = [('van_id', '=', van.id)]

        customer_id = _int_id(get_query_str('customerId'))
        if customer_id:
            domain.append(('partner_id', 'child_of', customer_id))

        status = (get_query_str('status') or '').strip().upper()
        if status == 'CANCELLED':
            domain.append(('state', '=', 'cancel'))
        elif status == 'INVOICED':
            domain += [('state', '!=', 'cancel'),
                       ('invoice_status', '=', 'invoiced')]
        elif status == 'CONFIRMED':
            domain += [('state', 'in', ('sale', 'done')),
                       ('invoice_status', '!=', 'invoiced')]
        elif status == 'DRAFT':
            domain.append(('state', 'in', ('draft', 'sent')))
        elif status:
            return app_error(
                "Unknown status. Use DRAFT, CONFIRMED, INVOICED or CANCELLED.",
                code=ErrCode.VALIDATION, status=400, field='status')

        records, pagination = paginate(
            'sale.order', domain,
            page=get_query_int('page', 1),
            limit=get_query_int('limit', 50), order='date_order desc, id desc')
        # Lines are omitted from the list, as the contract allows for routes:
        # a 50-order page with lines is a large payload on a weak connection.
        return app_response(
            data=[ser.order(o, with_lines=False) for o in records],
            pagination=pagination)

    @http.route(APP + '/orders/<string:order_id>', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def order_detail(self, order_id, **kw):
        van = app_van()
        if not van:
            return no_van_error()
        record = request.env['sale.order'].sudo().search(
            [('id', '=', _int_id(order_id)), ('van_id', '=', van.id)], limit=1)
        if not record:
            return app_error("Order not found for this van.",
                             code=ErrCode.NOT_FOUND, status=404, field='id')
        return app_response(data=ser.order(record))

    # =================================================================
    # INVOICES
    # =================================================================

    def _invoice_domain(self, van):
        partner_ids = app_partner_ids(van)
        return [
            ('move_type', '=', 'out_invoice'),
            ('company_id', '=', request.env.company.id),
            ('partner_id', 'in', list(partner_ids) or [0]),
        ]

    @http.route(APP + '/invoices', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def invoices(self, **kw):
        van = app_van()
        domain = self._invoice_domain(van)

        customer_id = _int_id(get_query_str('customerId'))
        if customer_id:
            domain.append(('partner_id', 'child_of', customer_id))

        status = (get_query_str('status') or '').strip().upper()
        if status == 'CANCELLED':
            domain.append(('state', '=', 'cancel'))
        elif status == 'PAID':
            domain += [('state', '=', 'posted'),
                       ('payment_state', 'in', ('paid', 'in_payment'))]
        elif status == 'PARTIALLY_PAID':
            domain += [('state', '=', 'posted'),
                       ('payment_state', '=', 'partial')]
        elif status == 'OPEN':
            domain += [('state', '=', 'posted'),
                       ('payment_state', '=', 'not_paid')]
        elif status:
            return app_error(
                "Unknown status. Use OPEN, PAID, PARTIALLY_PAID or CANCELLED.",
                code=ErrCode.VALIDATION, status=400, field='status')
        else:
            domain.append(('state', '!=', 'draft'))

        records, pagination = paginate(
            'account.move', domain,
            page=get_query_int('page', 1),
            limit=get_query_int('limit', 50), order='invoice_date_due, id')
        return app_response(
            data=[ser.invoice(m, with_lines=False) for m in records],
            pagination=pagination)

    @http.route(APP + '/invoices/<string:invoice_id>', type='http',
                auth='public', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def invoice_detail(self, invoice_id, **kw):
        van = app_van()
        record = request.env['account.move'].sudo().search(
            self._invoice_domain(van) + [('id', '=', _int_id(invoice_id))],
            limit=1)
        if not record:
            return app_error("Invoice not found for this van's customers.",
                             code=ErrCode.NOT_FOUND, status=404, field='id')
        return app_response(data=ser.invoice(record))

    # =================================================================
    # PAYMENTS
    # =================================================================

    @http.route(APP + '/payments', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def payments(self, **kw):
        van = app_van()
        if not van:
            return no_van_error()
        domain = [('collection_id.van_id', '=', van.id)]
        customer_id = _int_id(get_query_str('customerId'))
        if customer_id:
            domain.append(('collection_id.partner_id', 'child_of', customer_id))
        records, pagination = paginate(
            'van.sales.collection.line', domain,
            page=get_query_int('page', 1),
            limit=get_query_int('limit', 50), order='id desc')
        return app_response(data=[ser.payment(l) for l in records],
                            pagination=pagination)

    # =================================================================
    # GRN  -  goods received into the van
    # =================================================================

    @http.route(APP + '/grns', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def grns(self, **kw):
        van = app_van()
        if not van:
            return no_van_error()
        # A GRN is a receipt *into* the van. `?operation=all` widens to every
        # van transfer (returns and van-to-van moves) rather than hiding them.
        operations = (('load', 'unload', 'van_transfer')
                      if (get_query_str('operation') or '').lower() == 'all'
                      else ('load',))
        records, pagination = paginate(
            'stock.picking',
            [('van_id', '=', van.id), ('van_operation', 'in', operations)],
            page=get_query_int('page', 1),
            limit=get_query_int('limit', 50),
            order='scheduled_date desc, id desc')
        return app_response(data=[ser.grn(p) for p in records],
                            pagination=pagination)

    # =================================================================
    # VAN STOCK
    # =================================================================

    @http.route(APP + '/stock/van/<string:van_id>', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def van_stock(self, van_id, **kw):
        van = app_van()
        if not van:
            return no_van_error()
        # The van id in the path is checked against the caller's own van. A
        # salesman must not be able to read another van's stock by editing it.
        if _int_id(van_id) != van.id:
            return app_error("You can only read the stock of your own van.",
                             code=ErrCode.UNAUTHORIZED, status=403, field='vanId')

        quantities = van._van_sales_available_quantities()
        products = request.env['product.product'].sudo().browse(
            list(quantities)).exists()
        data = [ser.stock_item(p, van, quantities.get(p.id, 0.0))
                for p in products]
        data.sort(key=lambda row: (row['productCode'], row['productName']))
        return app_response(data=data)

    # =================================================================
    # ROUTES
    # =================================================================

    @http.route(APP + '/routes', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def routes(self, **kw):
        van = app_van()
        if not van:
            return no_van_error()
        records, pagination = paginate(
            'van.sales.visit.plan', [('van_id', '=', van.id)],
            page=get_query_int('page', 1),
            limit=get_query_int('limit', 50), order='date desc, id desc')
        # The contract allows the summary form to omit stops.
        return app_response(
            data=[ser.route(p, with_stops=False) for p in records],
            pagination=pagination)

    @http.route(APP + '/routes/today', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def route_today(self, **kw):
        van = app_van()
        if not van:
            return no_van_error()
        today = fields.Date.context_today(request.env.user)
        plans = request.env['van.sales.visit.plan'].sudo().search(
            [('van_id', '=', van.id), ('date', '=', today)], order='id')
        if not plans:
            return app_error(
                "No route is planned for this van today.",
                code=ErrCode.NOT_FOUND, status=404)
        # The contract assumes one route per salesman per day. Our model does
        # not: a van may serve several routes in a day, and `van.sales.visit
        # .plan` is unique per (route, date), not per (van, date). Returning
        # the first silently would hide the others, so the count travels with
        # the response and `/routes` lists them all.
        return app_response(
            data=ser.route(plans[0]),
            extra={'xPlanCountToday': len(plans)} if len(plans) > 1 else None)

    # =================================================================
    # NOTIFICATIONS
    # =================================================================

    @http.route(APP + '/notifications', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def notifications(self, **kw):
        domain = [('user_id', '=', request.env.user.id)]
        if get_query_bool('unreadOnly'):
            domain.append(('is_read', '=', False))
        records, pagination = paginate(
            'van.sales.notification', domain,
            page=get_query_int('page', 1),
            limit=get_query_int('limit', 50), order='create_date desc, id desc')
        unread = request.env['van.sales.notification'].sudo().search_count([
            ('user_id', '=', request.env.user.id), ('is_read', '=', False)])
        return app_response(
            data=[ser.notification(n) for n in records],
            pagination=pagination,
            extra={'xUnreadCount': unread})

    @http.route(APP + '/notifications/<string:notification_id>/read',
                type='http', auth='public', methods=['PUT', 'POST', 'OPTIONS'],
                csrf=False, cors='*')
    @app_token_required
    def notification_read(self, notification_id, **kw):
        record = request.env['van.sales.notification'].sudo().search(
            [('id', '=', _int_id(notification_id)),
             ('user_id', '=', request.env.user.id)], limit=1)
        if not record:
            return app_error("Notification not found.",
                             code=ErrCode.NOT_FOUND, status=404, field='id')
        if not record.is_read:
            record.is_read = True
        return app_response(data=None)

    @http.route(APP + '/notifications/read-all', type='http', auth='public',
                methods=['PUT', 'POST', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def notifications_read_all(self, **kw):
        records = request.env['van.sales.notification'].sudo().search([
            ('user_id', '=', request.env.user.id), ('is_read', '=', False)])
        records.write({'is_read': True})
        return app_response(data=None)
