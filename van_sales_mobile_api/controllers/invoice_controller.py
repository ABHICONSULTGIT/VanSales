# Part of the Van Sales project.

import logging

from odoo import Command, fields, http
from odoo.http import request

from .base import (
    API_PREFIX, ApiError, as_float, as_int, body, date_domain, date_param,
    fmt_date, get_own, me, money, my_van, ok, paginate, param, ref,
    require, token_required,
)

_logger = logging.getLogger(__name__)

INVOICE_TYPES = ('out_invoice', 'out_refund')


def invoice_list_item(move):
    currency = move.currency_id
    return {
        'id': move.id,
        'name': move.name,
        'type': 'invoice' if move.move_type == 'out_invoice' else 'credit_note',
        'date': fmt_date(move.invoice_date),
        'due_date': fmt_date(move.invoice_date_due),
        'customer': ref(move.partner_id),
        'total': money(move.amount_total, currency),
        'amount_due': money(move.amount_residual, currency),
        'state': move.state,
        'payment_state': move.payment_state,
    }


def invoice_detail(move):
    currency = move.currency_id
    data = invoice_list_item(move)
    payments = move.sudo()._get_reconciled_payments()
    data.update({
        'origin': move.invoice_origin or None,
        'lines': [{
            'product_id': line.product_id.id or None,
            'description': line.name or '',
            'qty': line.quantity,
            'price_unit': money(line.price_unit, currency),
            'subtotal': money(line.price_subtotal, currency),
        } for line in move.invoice_line_ids.filtered(
            lambda l: l.display_type == 'product')],
        'untaxed': money(move.amount_untaxed, currency),
        'tax': money(move.amount_tax, currency),
        'currency': currency.name,
        'payments': [{
            'name': p.name, 'date': fmt_date(p.date),
            'amount': money(p.amount, p.currency_id),
        } for p in payments],
    })
    return data


def collection_detail(collection):
    currency = collection.currency_id
    return {
        'id': collection.id,
        'name': collection.name,
        'date': fmt_date(collection.date),
        'customer': ref(collection.partner_id),
        'journal': collection.journal_id.name,
        'amount': money(collection.amount_total, currency),
        'state': collection.state,
        'memo': collection.memo or None,
        'allocations': [{
            'invoice_id': line.move_id.id,
            'invoice': line.move_id.name,
            'amount': money(line.amount, currency),
            'remaining_due': money(line.move_id.amount_residual, currency),
        } for line in collection.line_ids if line.amount],
    }


def collection_list_item(collection):
    return {
        'id': collection.id,
        'name': collection.name,
        'date': fmt_date(collection.date),
        'customer': ref(collection.partner_id),
        'amount': money(collection.amount_total, collection.currency_id),
        'state': collection.state,
    }


def my_invoices_domain():
    return [('move_type', 'in', INVOICE_TYPES), ('state', '!=', 'draft'),
            ('invoice_user_id', '=', me().id)]


def customer_filter(field='partner_id'):
    customer_id = param('customer_id')
    if not customer_id:
        return []
    partner = request.env['res.partner'].browse(
        as_int(customer_id, 'customer_id')).commercial_partner_id
    return [(field, 'child_of', partner.id)]


def collection_journals():
    company = request.env.company
    return request.env['account.journal'].search([
        ('type', 'in', ('cash', 'bank')), ('company_id', '=', company.id),
    ], order='type, sequence, id')


class VanSalesInvoiceController(http.Controller):

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    @http.route(API_PREFIX + '/invoices', type='http', auth='public',
                methods=['GET'], csrf=False, cors='*')
    @token_required
    def invoices(self, **kw):
        domain = my_invoices_domain() + customer_filter() + date_domain(
            'invoice_date', date_param('date_from'), date_param('date_to'))
        payment_state = param('payment_state')
        if payment_state:
            domain.append(('payment_state', '=', payment_state))
        moves, page = paginate(request.env['account.move'], domain,
                               order='invoice_date desc, id desc')
        return ok([invoice_list_item(m) for m in moves], pagination=page)

    @http.route(API_PREFIX + '/invoices/<int:move_id>', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    @token_required
    def invoice(self, move_id, **kw):
        return ok(invoice_detail(
            get_own('account.move', move_id, my_invoices_domain())))

    @http.route(API_PREFIX + '/invoices/<int:move_id>/pdf', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    @token_required
    def invoice_pdf(self, move_id, **kw):
        move = get_own('account.move', move_id, my_invoices_domain())
        try:
            # sudo: rendering reads company, tax and journal data the salesman
            # has no rights on. The invoice itself was access-checked above.
            pdf, _type = request.env['ir.actions.report'].sudo() \
                ._render_qweb_pdf('account.account_invoices', [move.id])
        except Exception:
            _logger.exception("Invoice PDF failed for %s", move.id)
            raise ApiError("The invoice PDF could not be generated on the "
                           "server.", 500)
        filename = '%s.pdf' % (move.name or 'invoice').replace('/', '_')
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Length', str(len(pdf))),
            ('Content-Disposition', 'inline; filename="%s"' % filename),
        ])

    # ------------------------------------------------------------------
    # Payments (van cash collections)
    # ------------------------------------------------------------------
    @http.route(API_PREFIX + '/payments/journals', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    @token_required
    def journals(self, **kw):
        default = request.env['van.sales.collection']._default_journal_id()
        return ok([{'id': j.id, 'name': j.name, 'type': j.type,
                    'is_default': j == default}
                   for j in collection_journals()])

    @http.route(API_PREFIX + '/payments', type='http', auth='public',
                methods=['GET'], csrf=False, cors='*')
    @token_required
    def payments(self, **kw):
        domain = [('salesman_user_id', '=', me().id)] + customer_filter() + \
            date_domain('date', date_param('date_from'), date_param('date_to'))
        collections, page = paginate(request.env['van.sales.collection'],
                                     domain, order='date desc, id desc')
        return ok([collection_list_item(c) for c in collections],
                  pagination=page)

    @http.route(API_PREFIX + '/payments/<int:collection_id>', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    @token_required
    def payment(self, collection_id, **kw):
        return ok(collection_detail(get_own(
            'van.sales.collection', collection_id,
            [('salesman_user_id', '=', me().id)])))

    @http.route(API_PREFIX + '/payments', type='http', auth='public',
                methods=['POST'], csrf=False, cors='*')
    @token_required
    def create_payment(self, **kw):
        data = body()
        require(data, 'customer_id', 'allocations')
        van = my_van()
        Collection = request.env['van.sales.collection']

        client_uuid = (data.get('client_uuid') or '').strip() or False
        if client_uuid:
            existing = Collection.search(
                [('van_client_uuid', '=', client_uuid)], limit=1)
            if existing:
                return ok(collection_detail(existing), "Payment already received.")

        partner = request.env['res.partner'].search(
            [('id', '=', as_int(data['customer_id'], 'customer_id'))], limit=1)
        if not partner:
            raise ApiError("Customer not found.", 404)

        allocations = data['allocations']
        if not isinstance(allocations, list) or not allocations:
            raise ApiError("'allocations' must be a non-empty list.")
        lines, seen = [], set()
        for index, item in enumerate(allocations, start=1):
            if not isinstance(item, dict):
                raise ApiError("Allocation %s must be an object." % index)
            invoice_id = as_int(item.get('invoice_id'), 'invoice_id')
            if invoice_id in seen:
                raise ApiError("Invoice %s is listed twice." % invoice_id)
            seen.add(invoice_id)
            invoice = request.env['account.move'].search([
                ('id', '=', invoice_id), ('move_type', '=', 'out_invoice')],
                limit=1)
            if not invoice:
                raise ApiError("Invoice %s not found." % invoice_id, 404)
            lines.append(Command.create({
                'move_id': invoice.id,
                'amount': as_float(item.get('amount'), 'amount'),
            }))

        values = {
            'partner_id': partner.id,
            'van_id': van.id,
            'line_ids': lines,
            'memo': data.get('memo') or False,
            'van_client_uuid': client_uuid,
        }
        if data.get('journal_id'):
            journal = collection_journals().filtered(
                lambda j: j.id == as_int(data['journal_id'], 'journal_id'))
            if not journal:
                raise ApiError("Journal not found.", 404)
        else:
            journal = Collection._default_journal_id()
            if not journal:
                raise ApiError("No cash journal is set up for your company.",
                               409)
        values['journal_id'] = journal.id
        if data.get('date'):
            try:
                values['date'] = fields.Date.to_date(data['date'])
            except ValueError:
                raise ApiError("'date' must be a date as YYYY-MM-DD.")
        collection = Collection.create(values)
        # The backend's own checks: invoice posted, same customer, same
        # currency, amount not above what is still owed.
        collection.action_post()
        return ok(collection_detail(collection), "Payment recorded.",
                  status=201)
