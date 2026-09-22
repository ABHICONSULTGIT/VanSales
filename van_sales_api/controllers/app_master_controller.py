# Part of the Van Sales project.
"""Customers, products and company settings, in the mobile contract's shape.

Read-only. Every customer query is scoped by :func:`app_base.app_partner_domain`
to the customers on this van's routes - the same rule the sync layer applies -
so a REST wrapper can never return a customer the app would not have received
through ``sync/pull``.
"""

from odoo import http
from odoo.http import request

from . import app_serializers as ser
from .base import ErrCode, get_query_int, get_query_str, paginate
from .app_base import (app_error, app_partner_domain, app_response,
                       app_token_required, app_van, no_van_error)

APP = '/api/v1/app'


def _int_id(raw):
    """Contract ids are opaque strings; ours are integers underneath."""
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def _bad_id(raw):
    """A clean 400 for an unusable id.

    Without this, `/customers/abc/orders` would run a domain on id 0 and
    answer `200 []` - telling the salesman this customer has no orders, when
    in fact the request was malformed. An empty list and a bad request must
    not look the same.
    """
    return app_error("Invalid customer id.", code=ErrCode.VALIDATION,
                     status=400, field='id')


def _route_map(van):
    """{partner_id: (route_master_id, route_name)} for this van, in one query.

    Prefetched so serialising 200 customers does not run 200 route lookups.
    """
    if not van:
        return {}
    lines = request.env['van.sales.route.line'].sudo().search([
        ('route_id.van_id', '=', van.id),
        ('partner_id', '!=', False),
    ], order='route_id, sequence, id')
    mapping = {}
    for line in lines:
        # First route wins when a customer appears on more than one.
        mapping.setdefault(
            line.partner_id.id,
            (line.route_id.id, line.route_id.display_name))
    return mapping


class VanSalesAppMasterController(http.Controller):

    # =================================================================
    # CUSTOMERS
    # =================================================================

    @http.route(APP + '/customers', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def customers(self, **kw):
        van = app_van()
        domain = app_partner_domain(van)

        search = (get_query_str('search') or '').strip()
        if search:
            domain += ['|', '|',
                       ('name', 'ilike', search),
                       ('ref', 'ilike', search),
                       ('phone', 'ilike', search)]

        route_id = _int_id(get_query_str('routeId'))
        if route_id:
            lines = request.env['van.sales.route.line'].sudo().search([
                ('route_id', '=', route_id), ('partner_id', '!=', False)])
            domain.append(('id', 'in', lines.mapped('partner_id').ids or [0]))

        # `area` has no source in Odoo. Reported as ignored rather than
        # silently dropped, so the app never believes a filter was applied.
        ignored = ['area'] if get_query_str('area') else []

        records, pagination = paginate(
            'res.partner', domain,
            page=get_query_int('page', 1),
            limit=get_query_int('limit', 50), order='name, id')
        route_map = _route_map(van)
        return app_response(
            data=[ser.customer(p, route_map) for p in records],
            pagination=pagination,
            extra={'xIgnoredFilters': ignored} if ignored else None)

    @http.route(APP + '/customers/<string:customer_id>', type='http',
                auth='public', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def customer_detail(self, customer_id, **kw):
        van = app_van()
        partner = request.env['res.partner'].sudo().search(
            app_partner_domain(van) + [('id', '=', _int_id(customer_id))], limit=1)
        if not partner:
            return app_error("Customer not found, or not on this van's routes.",
                             code=ErrCode.NOT_FOUND, status=404, field='id')
        return app_response(data=ser.customer(partner, _route_map(van)))

    @http.route(APP + '/customers/<string:customer_id>/orders', type='http',
                auth='public', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def customer_orders(self, customer_id, **kw):
        van = app_van()
        if not van:
            return no_van_error()
        partner_id = _int_id(customer_id)
        if not partner_id:
            return _bad_id(customer_id)
        records, pagination = paginate(
            'sale.order',
            [('van_id', '=', van.id), ('partner_id', 'child_of', partner_id)],
            page=get_query_int('page', 1),
            limit=get_query_int('limit', 50), order='date_order desc, id desc')
        return app_response(
            data=[ser.order(o, with_lines=False) for o in records],
            pagination=pagination)

    @http.route(APP + '/customers/<string:customer_id>/payments', type='http',
                auth='public', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def customer_payments(self, customer_id, **kw):
        van = app_van()
        if not van:
            return no_van_error()
        partner_id = _int_id(customer_id)
        if not partner_id:
            return _bad_id(customer_id)
        records, pagination = paginate(
            'van.sales.collection.line',
            [('collection_id.van_id', '=', van.id),
             ('collection_id.partner_id', 'child_of', partner_id)],
            page=get_query_int('page', 1),
            limit=get_query_int('limit', 50),
            order='id desc')
        return app_response(data=[ser.payment(l) for l in records],
                            pagination=pagination)

    @http.route(APP + '/customers/<string:customer_id>/visits', type='http',
                auth='public', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def customer_visits(self, customer_id, **kw):
        van = app_van()
        if not van:
            return no_van_error()
        partner_id = _int_id(customer_id)
        if not partner_id:
            return _bad_id(customer_id)
        records, pagination = paginate(
            'van.sales.visit',
            [('van_id', '=', van.id), ('partner_id', 'child_of', partner_id)],
            page=get_query_int('page', 1),
            limit=get_query_int('limit', 50), order='date desc, sequence, id')
        return app_response(data=[ser.route_stop(v) for v in records],
                            pagination=pagination)

    # =================================================================
    # PRODUCTS
    # =================================================================

    @http.route(APP + '/products', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def products(self, **kw):
        # Company filter matters: these endpoints run sudo(), which bypasses
        # record rules, so multi-company isolation has to be explicit here. A
        # salesman must not see another company's catalogue.
        domain = [('sale_ok', '=', True), ('type', '=', 'consu'),
                  ('company_id', 'in', (False, request.env.company.id))]

        barcode = (get_query_str('barcode') or '').strip()
        if barcode:
            domain.append(('barcode', '=', barcode))

        search = (get_query_str('search') or '').strip()
        if search:
            domain += ['|', '|',
                       ('name', 'ilike', search),
                       ('default_code', 'ilike', search),
                       ('barcode', '=', search)]

        category_id = _int_id(get_query_str('categoryId'))
        if category_id:
            domain.append(('categ_id', 'child_of', category_id))

        records, pagination = paginate(
            'product.product', domain,
            page=get_query_int('page', 1),
            limit=get_query_int('limit', 50), order='default_code, name, id')
        return app_response(data=[ser.product(p) for p in records],
                            pagination=pagination)

    @http.route(APP + '/products/<string:product_id>', type='http',
                auth='public', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def product_detail(self, product_id, **kw):
        record = request.env['product.product'].sudo().search(
            [('id', '=', _int_id(product_id)), ('sale_ok', '=', True),
             ('company_id', 'in', (False, request.env.company.id))], limit=1)
        if not record:
            return app_error("Product not found.", code=ErrCode.NOT_FOUND,
                             status=404, field='id')
        return app_response(data=ser.product(record))

    @http.route(APP + '/categories', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def categories(self, **kw):
        records, pagination = paginate(
            'product.category', [],
            page=get_query_int('page', 1),
            limit=get_query_int('limit', 100), order='complete_name, id')
        # One grouped query for the whole page, not a `child_of` count per
        # category: 100 hierarchy counts would make this the slowest endpoint
        # in the API for no reason. Counts are direct (not rolled up through
        # child categories), which is what the contract's `productCount` means.
        # _read_group, not read_group: the latter is marked Deprecated in
        # Odoo 19 and returns the older dict shape.
        grouped = request.env['product.product'].sudo()._read_group(
            [('categ_id', 'in', records.ids), ('sale_ok', '=', True),
             ('type', '=', 'consu'),
             ('company_id', 'in', (False, request.env.company.id))],
            groupby=['categ_id'], aggregates=['__count'])
        counts = {categ.id: count for categ, count in grouped if categ}
        return app_response(
            data=[ser.category(c, counts.get(c.id, 0)) for c in records],
            pagination=pagination)

    @http.route(APP + '/price-lists', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def price_lists(self, **kw):
        records, pagination = paginate(
            'product.pricelist',
            [('company_id', 'in', (False, request.env.company.id))],
            page=get_query_int('page', 1),
            limit=get_query_int('limit', 50), order='name, id')
        return app_response(data=[ser.pricelist(p) for p in records],
                            pagination=pagination)

    # =================================================================
    # SETTINGS
    # =================================================================

    @http.route(APP + '/settings/company', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @app_token_required
    def settings_company(self, **kw):
        return app_response(data=ser.company_settings(request.env.company))
