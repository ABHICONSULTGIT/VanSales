# Part of the Van Sales project.
"""Live lookups for the cases the cached dataset cannot cover.

Everything the app needs day to day comes down through sync. These are for the
edges: a customer who is not on the route, a barcode the cache does not know,
and a fresh read of what the van is actually carrying.
"""

from odoo import http
from odoo.http import request

from .base import (current_device, current_van, get_query_int, get_query_str,
                   paginate, success_response, token_required, device_required,
                   _f, _i, _m2o, _s)


class VanSalesLookupController(http.Controller):

    @http.route('/api/v1/lookup/customers', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    def customers(self, **kw):
        query = (get_query_str('q') or '').strip()
        domain = [('company_id', 'in', (False, request.env.company.id))]
        if query:
            domain += ['|', '|',
                       ('name', 'ilike', query),
                       ('ref', 'ilike', query),
                       ('phone', 'ilike', query)]
        records, pagination = paginate(
            'res.partner', domain,
            page=get_query_int('page', 1),
            limit=get_query_int('limit', 30), order='name, id')
        return success_response(
            data=[{
                'id': _i(p.id),
                'name': _s(p.name),
                'ref': _s(p.ref),
                'phone': _s(p.phone),
                'city': _s(p.city),
                'credit_limit': _f(p.credit_limit),
                'balance': _f(p.credit),
            } for p in records.sudo()],
            pagination=pagination)

    @http.route('/api/v1/lookup/products', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    def products(self, **kw):
        query = (get_query_str('q') or '').strip()
        domain = [('sale_ok', '=', True), ('type', '=', 'consu')]
        if query:
            domain += ['|', '|',
                       ('name', 'ilike', query),
                       ('default_code', 'ilike', query),
                       ('barcode', '=', query)]
        records, pagination = paginate(
            'product.product', domain,
            page=get_query_int('page', 1),
            limit=get_query_int('limit', 30), order='default_code, name, id')
        van = current_van()
        on_van = van._van_sales_available_quantities(records) if van else {}
        return success_response(
            data=[{
                'id': _i(p.id),
                'name': _s(p.name),
                'default_code': _s(p.default_code),
                'barcode': _s(p.barcode),
                'uom': _m2o(p.uom_id),
                'price': _f(p.lst_price),
                'on_van': _f(on_van.get(p.id, 0.0)),
                'stock_policy': _s(p.van_sale_stock_policy_effective),
            } for p in records.sudo()],
            pagination=pagination)

    @http.route('/api/v1/lookup/van-stock', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    @device_required
    def van_stock(self, **kw):
        van = current_device().van_id
        quantities = van._van_sales_available_quantities()
        products = request.env['product.product'].sudo().browse(
            list(quantities)).exists()
        return success_response(data={
            'van': _m2o(van),
            'location': _m2o(van.van_location_id),
            'lines': [{
                'product_id': _i(p.id),
                'name': _s(p.name),
                'default_code': _s(p.default_code),
                'uom': _m2o(p.uom_id),
                'quantity': _f(quantities.get(p.id, 0.0)),
            } for p in products],
        })

    @http.route('/api/v1/lookup/open-invoices', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    def open_invoices(self, **kw):
        partner_id = get_query_int('partner_id')
        domain = [
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('company_id', '=', request.env.company.id),
        ]
        if partner_id:
            domain.append(('partner_id', 'child_of', partner_id))
        records, pagination = paginate(
            'account.move', domain,
            page=get_query_int('page', 1),
            limit=get_query_int('limit', 50),
            order='invoice_date_due, id')
        return success_response(
            data=[{
                'id': _i(m.id),
                'name': _s(m.name),
                'partner': _m2o(m.partner_id),
                'invoice_date': _s(m.invoice_date),
                'date_due': _s(m.invoice_date_due),
                'amount_total': _f(m.amount_total),
                'amount_residual': _f(m.amount_residual),
                'currency': _m2o(m.currency_id),
                'payment_state': _s(m.payment_state),
            } for m in records.sudo()],
            pagination=pagination)
