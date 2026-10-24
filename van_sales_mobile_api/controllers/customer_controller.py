# Part of the Van Sales project.

from odoo import http
from odoo.http import request

from .base import (
    API_PREFIX, ApiError, body, fmt_date, fmt_datetime, get_own, me, money,
    ok, paginate, param, require, token_required, today,
)

# Decision D1: the app may set exactly these on a customer, nothing else.
EDITABLE_FIELDS = {
    'name': 'name', 'phone': 'phone', 'email': 'email', 'street': 'street',
    'city': 'city', 'vat': 'vat', 'latitude': 'partner_latitude',
    'longitude': 'partner_longitude',
}


def my_customers_domain():
    return [('user_id', '=', me().id), ('parent_id', '=', False)]


def reachable_domain():
    """Customers he may open: his own, plus anyone on his visit plans or
    orders (a route stop can be a customer assigned to another salesman)."""
    user = me()
    visited = request.env['van.sales.visit'].search(
        [('salesman_user_id', '=', user.id), ('partner_id', '!=', False)]
    ).partner_id.commercial_partner_id
    ordered = request.env['sale.order'].search(
        [('user_id', '=', user.id)]).partner_id.commercial_partner_id
    return ['|', ('user_id', '=', user.id),
            ('commercial_partner_id', 'in', (visited | ordered).ids)]


def balances(partners):
    """Receivable per customer.

    sudo: the true balance includes invoices raised by the office, which the
    salesman's own-documents rule hides from him. Read for his customers only.
    """
    return {p.id: p.credit for p in partners.sudo()}


def customer_list_item(partner, balance):
    return {
        'id': partner.id,
        'name': partner.name,
        'phone': partner.phone or None,
        'city': partner.city or None,
        'balance_due': money(balance),
    }


def customer_detail(partner):
    Move = request.env['account.move'].sudo()
    commercial = partner.commercial_partner_id
    open_domain = [
        ('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
        ('payment_state', 'in', ('not_paid', 'partial')),
        ('commercial_partner_id', '=', commercial.id),
    ]
    open_invoices = Move.search(open_domain)
    overdue = open_invoices.filtered(
        lambda m: m.invoice_date_due and m.invoice_date_due < today())

    Order = request.env['sale.order']
    order_domain = [('partner_id', 'child_of', commercial.id),
                    ('state', '=', 'sale')]
    [(count, total)] = Order._read_group(
        order_domain, [], ['__count', 'amount_total:sum'])
    recent = Order.search([('partner_id', 'child_of', commercial.id)],
                          order='date_order desc, id desc', limit=5)

    # sudo: same reason as the balance - payments by any channel count.
    last_payment = request.env['account.payment'].sudo().search([
        ('partner_id', 'child_of', commercial.id),
        ('payment_type', '=', 'inbound'), ('state', 'in', ('paid', 'in_process')),
    ], order='date desc, id desc', limit=1)

    return {
        'id': partner.id,
        'name': partner.name,
        'phone': partner.phone or None,
        'email': partner.email or None,
        'street': partner.street or None,
        'city': partner.city or None,
        'vat': partner.vat or None,
        'latitude': partner.partner_latitude or None,
        'longitude': partner.partner_longitude or None,
        'credit_limit': money(partner.sudo().credit_limit),
        'balance_due': money(partner.sudo().credit),
        'invoices': {
            'open': len(open_invoices),
            'overdue': len(overdue),
            'amount_due': money(sum(open_invoices.mapped('amount_residual'))),
        },
        'orders': {
            'count': count,
            'total': money(total),
            'recent': [{
                'id': o.id, 'name': o.name, 'date': fmt_datetime(o.date_order),
                'state': o.state,
                'amount': money(o.amount_total, o.currency_id),
            } for o in recent],
        },
        'last_payment': {
            'date': fmt_date(last_payment.date),
            'amount': money(last_payment.amount, last_payment.currency_id),
        } if last_payment else None,
    }


def customer_values(data, creating):
    values = {}
    for key, field in EDITABLE_FIELDS.items():
        if key not in data:
            continue
        value = data[key]
        if field in ('partner_latitude', 'partner_longitude'):
            if value in (None, ''):
                value = 0.0
            else:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    raise ApiError("'%s' must be a number." % key)
                limit = 90 if key == 'latitude' else 180
                if not -limit <= value <= limit:
                    raise ApiError("'%s' is out of range." % key)
        else:
            value = (str(value).strip() if value is not None else '') or False
        values[field] = value
    if 'name' in values and not values['name']:
        raise ApiError("The customer name cannot be empty.")
    if creating:
        values['is_company'] = bool(data.get('is_company', True))
    return values


class VanSalesCustomerController(http.Controller):

    @http.route(API_PREFIX + '/customers', type='http', auth='public',
                methods=['GET'], csrf=False, cors='*')
    @token_required
    def list(self, **kw):
        domain = my_customers_domain()
        search = (param('search') or '').strip()
        if search:
            domain = domain + [
                '|', '|', ('name', 'ilike', search), ('phone', 'ilike', search),
                ('ref', 'ilike', search)]
        partners, page = paginate(request.env['res.partner'], domain,
                                  order='name, id')
        due = balances(partners)
        return ok([customer_list_item(p, due[p.id]) for p in partners],
                  pagination=page)

    @http.route(API_PREFIX + '/customers/<int:partner_id>', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    @token_required
    def detail(self, partner_id, **kw):
        partner = get_own('res.partner', partner_id, reachable_domain())
        return ok(customer_detail(partner))

    @http.route(API_PREFIX + '/customers', type='http', auth='public',
                methods=['POST'], csrf=False, cors='*')
    @token_required
    def create(self, **kw):
        data = body()
        require(data, 'name')
        values = customer_values(data, creating=True)
        values.update({
            'user_id': me().id,
            'customer_rank': 1,
            'company_id': request.env.company.id,
        })
        # sudo (decision D1): the salesman holds no Contact Creation right.
        # The values are the whitelist above, the customer is his, and the
        # record is read back as him below.
        partner = request.env['res.partner'].sudo().create(values)
        partner = partner.with_env(request.env)
        return ok(customer_detail(partner), "Customer created.", status=201)

    @http.route(API_PREFIX + '/customers/<int:partner_id>', type='http',
                auth='public', methods=['PUT'], csrf=False, cors='*')
    @token_required
    def update(self, partner_id, **kw):
        partner = get_own('res.partner', partner_id, my_customers_domain())
        values = customer_values(body(), creating=False)
        if not values:
            raise ApiError("Nothing to update.")
        # sudo (decision D1): his own customer only (domain above), whitelisted
        # fields only.
        partner.sudo().write(values)
        return ok(customer_detail(partner), "Customer updated.")
