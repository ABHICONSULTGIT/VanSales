# Part of the Van Sales project.
"""Record -> mobile-contract dict.

One function per entity in the *Vantix Van Sales API Specification v1.0*. Each
returns exactly the field names that document lists, in ``camelCase``, with
string identifiers.

Where a contract field has nothing behind it in Odoo today, it is emitted with
a neutral value **and named in the module docstring below** - never quietly
invented. Additional keys prefixed with ``x`` (or obviously ours, like
``nativeType``) carry information the contract has no slot for, so nothing is
lost while the two specifications are being reconciled. Extra keys are
additive and safe: a client model ignores what it does not declare.

Contract fields with no source in Odoo today
--------------------------------------------
``Customer.contactPerson``   no field (res.partner.child_ids exists but which
                             child is "the" contact is undecided) -> ''
``Customer.area``            no field -> ''
``Product.minOrderQty``      no field -> 0 (there is genuinely no minimum)
``SalesOrder.totalFoc``      free-of-charge is not built (decision D-07) -> 0
``SalesOrderLine.focQty``    same -> 0
``SalesOrder.signatureUrl``  no Binary/Image field exists anywhere in the four
``SalesOrder.photoUrl``      modules; proof of delivery is unbuilt -> ''
``SalesOrder.customerNotes`` only one note field exists -> ''
``Invoice.pdfUrl``           no report layout built -> None
``Payment.receiptUrl``       no report layout built -> None
``Payment.retryCount``       a client-side counter -> 0
``RouteStop.plannedTime``    stops are sequenced, not time-tabled -> None
``RouteStop.area``           see Customer.area -> ''
``GRNLine.reason``           ours is per *picking*, theirs per line -> None
``GRNLine.photoUrl``         no attachment support -> None
``syncedAt`` (everywhere)    would need a sync-log join per row -> None
"""

from odoo.http import request

from .base import image_url
from .app_base import b, dt, f, i, opt, s, sid

# =============================================================================
# ENUM MAPPING  -  our stored values -> the contract's
# =============================================================================

VISIT_STATUS = {
    'planned': 'PLANNED',
    'checked_in': 'CHECKED_IN',
    'done': 'CHECKED_OUT',          # one-to-one: "done" *is* checked out
    'skipped': 'SKIPPED',
}

# The contract's NotificationType has no slot for two of ours. Rather than
# dropping them (a van-load alert would vanish) they are folded into
# ANNOUNCEMENT and the true value is carried in `nativeType`. The contract
# should gain VAN_LOAD_READY; until it does, nothing is lost.
NOTIFICATION_TYPE = {
    'plan': 'ROUTE_CHANGE',
    'approval': 'ORDER_APPROVAL',
    'stock': 'LOW_STOCK',
    'announcement': 'ANNOUNCEMENT',
    'load': 'ANNOUNCEMENT',
    'system': 'ANNOUNCEMENT',
}

PAYMENT_METHOD = {'cash': 'CASH', 'bank': 'BANK'}


def order_status(order):
    if order.state == 'cancel':
        return 'CANCELLED'
    if order.invoice_status == 'invoiced':
        return 'INVOICED'
    if order.state in ('sale', 'done'):
        return 'CONFIRMED'
    return 'DRAFT'


def invoice_status(move):
    if move.state == 'cancel':
        return 'CANCELLED'
    if move.payment_state in ('paid', 'in_payment'):
        return 'PAID'
    if move.payment_state == 'partial':
        return 'PARTIALLY_PAID'
    return 'OPEN'


def grn_status(picking):
    if picking.state == 'done':
        return 'DISCREPANCY' if picking.van_has_discrepancy else 'CONFIRMED'
    return 'PENDING'


# =============================================================================
# MASTERS
# =============================================================================

def customer(partner, route_map=None):
    """``route_map``: {partner_id: (route_id, route_name)}, prefetched by the
    caller so a list of 200 customers does not run 200 route queries."""
    route_id, route_name = (route_map or {}).get(partner.id, ('', ''))
    address = ', '.join(part for part in (partner.street, partner.street2) if part)
    pricelist = partner.property_product_pricelist
    return {
        'id': sid(partner.id),
        'code': s(partner.ref),
        'name': s(partner.name),
        'contactPerson': '',
        'phone': s(partner.phone),
        'email': s(partner.email),
        'address': address,
        'city': s(partner.city),
        'state': s(partner.state_id.display_name) if partner.state_id else '',
        'pincode': s(partner.zip),
        'latitude': f(partner.partner_latitude),
        'longitude': f(partner.partner_longitude),
        'creditLimit': f(partner.credit_limit),
        'outstandingBalance': f(partner.credit),
        'priceListId': sid(pricelist.id) if pricelist else '',
        'priceListName': s(pricelist.display_name) if pricelist else '',
        'taxId': s(partner.vat),
        'routeId': sid(route_id) if route_id else '',
        'routeName': s(route_name),
        'area': '',
        'active': b(partner.active),
    }


def _product_taxes(product):
    """Percentage rate and price-included flag for the company's sale taxes.

    A single number cannot express a compound, fixed-amount or fiscal-position
    tax, so the tax **ids** travel alongside in ``xTaxIds`` and the server
    stays authoritative for every computed total.
    """
    company = request.env.company
    taxes = product.taxes_id.filtered(
        lambda t: not t.company_id or t.company_id == company)
    rate = sum(t.amount for t in taxes if t.amount_type == 'percent')
    included = any(t.price_include_override == 'tax_included' for t in taxes)
    return rate, included, taxes.ids


def product(record):
    rate, included, tax_ids = _product_taxes(record)
    uom_name = s(record.uom_id.display_name) if record.uom_id else ''
    return {
        'id': sid(record.id),
        'code': s(record.default_code),
        'name': s(record.name),
        'description': s(record.description_sale),
        'categoryId': sid(record.categ_id.id) if record.categ_id else '',
        'categoryName': s(record.categ_id.display_name) if record.categ_id else '',
        'barcode': s(record.barcode),
        # Odoo serves a placeholder when a product has no image, so this is
        # always a usable URL. It is /web/image/... - see the README note on
        # image access for a bearer-token client.
        'imageUrl': image_url('product.product', record.id, 'image_256'),
        # The contract carries both `unit` and `uom`; Odoo has one unit of
        # measure. Both are filled from it until the mobile team says what
        # they intend the difference to be.
        'unit': uom_name,
        'uom': uom_name,
        'price': f(record.lst_price),
        'taxRate': f(rate),
        'taxIncluded': b(included),
        'minOrderQty': 0,
        'active': b(record.active),
        'xTaxIds': [sid(t) for t in tax_ids],
        'xStockPolicy': s(record.van_sale_stock_policy_effective),
    }


def category(record, product_count=0):
    return {
        'id': sid(record.id),
        'name': s(record.name),
        'parentId': sid(record.parent_id.id) if record.parent_id else None,
        'productCount': i(product_count),
    }


def pricelist(record):
    return {
        'id': sid(record.id),
        'name': s(record.name),
        'currency': s(record.currency_id.name),
        'active': b(record.active),
    }


# =============================================================================
# DOCUMENTS
# =============================================================================

def order_line(line):
    return {
        'id': sid(line.id),
        'productId': sid(line.product_id.id) if line.product_id else '',
        'productCode': s(line.product_id.default_code),
        'productName': s(line.product_id.display_name or line.name),
        'qty': f(line.product_uom_qty),
        'unitPrice': f(line.price_unit),
        'discount': f(line.discount),
        'discountType': 'PERCENT',       # Odoo's sale line has no amount discount
        'taxRate': f(sum(t.amount for t in line.tax_ids
                         if t.amount_type == 'percent')),
        'focQty': 0.0,
        'lineTotal': f(line.price_total),
        'unit': s(line.product_uom_id.display_name) if line.product_uom_id else '',
    }


def order(record, with_lines=True):
    lines = record.order_line.filtered(lambda l: not l.display_type)
    total_discount = sum(
        (l.price_unit * l.product_uom_qty) * (l.discount or 0.0) / 100.0
        for l in lines)
    invoice = record.invoice_ids[:1]
    payload = {
        'id': sid(record.id),
        'clientUuid': s(record.van_client_uuid),
        'orderNumber': s(record.name),
        'customerId': sid(record.partner_id.id) if record.partner_id else '',
        'customerName': s(record.partner_id.display_name),
        'salesmanId': sid(record.van_salesman_user_id.id)
                      if record.van_salesman_user_id else '',
        'date': dt(record.date_order),
        'subtotal': f(record.amount_untaxed),
        'totalDiscount': f(total_discount),
        'totalTax': f(record.amount_tax),
        'totalFoc': 0.0,
        'grandTotal': f(record.amount_total),
        'notes': s(record.note),
        'customerNotes': '',
        'status': order_status(record),
        'syncStatus': 'SYNCED',
        'invoiceId': sid(invoice.id) if invoice else None,
        'signatureUrl': '',
        'photoUrl': '',
        'createdAt': dt(record.create_date),
        'syncedAt': None,
        'xVanId': sid(record.van_id.id) if record.van_id else '',
        'xVisitId': sid(record.van_visit_id.id) if record.van_visit_id else '',
        'xCurrency': s(record.currency_id.name),
    }
    if with_lines:
        payload['lines'] = [order_line(l) for l in lines]
    return payload


def invoice_line(line):
    return {
        'id': sid(line.id),
        'productId': sid(line.product_id.id) if line.product_id else '',
        'productName': s(line.product_id.display_name or line.name),
        'qty': f(line.quantity),
        'unitPrice': f(line.price_unit),
        'taxRate': f(sum(t.amount for t in line.tax_ids
                         if t.amount_type == 'percent')),
        'lineTotal': f(line.price_total),
    }


def invoice(record, with_lines=True):
    sale_orders = record.invoice_line_ids.sale_line_ids.order_id[:1]
    payload = {
        'id': sid(record.id),
        'clientUuid': s(record.van_client_uuid),
        'invoiceNumber': s(record.name),
        'customerId': sid(record.partner_id.id) if record.partner_id else '',
        'customerName': s(record.partner_id.display_name),
        'date': dt(record.invoice_date),
        'dueDate': dt(record.invoice_date_due),
        'subtotal': f(record.amount_untaxed),
        'totalTax': f(record.amount_tax),
        'total': f(record.amount_total),
        'amountPaid': f(record.amount_total - record.amount_residual),
        'balance': f(record.amount_residual),
        'status': invoice_status(record),
        'orderId': sid(sale_orders.id) if sale_orders else None,
        'pdfUrl': None,
        'syncStatus': 'SYNCED',
        'createdAt': dt(record.create_date),
        'xCurrency': s(record.currency_id.name),
    }
    if with_lines:
        payload['lines'] = [
            invoice_line(l) for l in record.invoice_line_ids
            if not l.display_type and l.product_id]
    return payload


def payment(line):
    """One **collection line** becomes one contract ``Payment``.

    Our ``van.sales.collection`` is one receipt allocated across several
    invoices, because that is what a salesman actually does and because
    ``reconcile()`` is FIFO-by-due-date and cannot be told otherwise. The
    contract's Payment carries a single ``invoiceId``, so each allocation is
    reported separately and ``xCollectionId`` lets the app group them back
    into the receipt the customer was handed.
    """
    collection = line.collection_id
    journal_type = collection.journal_id.type
    return {
        'id': sid(line.id),
        'clientUuid': s(collection.van_client_uuid),
        'paymentNumber': s(collection.name),
        'customerId': sid(collection.partner_id.id) if collection.partner_id else '',
        'customerName': s(collection.partner_id.display_name),
        'invoiceId': sid(line.move_id.id) if line.move_id else None,
        'invoiceNumber': opt(line.move_id.name) if line.move_id else None,
        'amount': f(line.amount),
        'method': PAYMENT_METHOD.get(journal_type, 'OTHER'),
        'reference': opt(collection.memo),
        'date': dt(collection.date),
        'salesmanId': sid(collection.salesman_user_id.id)
                      if collection.salesman_user_id else '',
        'syncStatus': 'SYNCED',
        'retryCount': 0,
        'receiptUrl': None,
        'createdAt': dt(collection.create_date),
        'syncedAt': None,
        'xCollectionId': sid(collection.id),
        'xCollectionTotal': f(collection.amount_total),
        'xJournal': s(collection.journal_id.display_name),
        'xState': s(collection.state),
    }


# =============================================================================
# ROUTES AND VISITS
# =============================================================================

def route_stop(visit):
    """A visit as a contract ``RouteStop``.

    The contract makes ``customerId``/``customerName`` mandatory, so it cannot
    express a **location stop** - a van parking somewhere and selling to
    whoever comes, which is half of what the client confirmed they need. For
    those stops ``customerId`` is empty and ``customerName`` carries the
    location's name so the app shows something meaningful; ``xStopType``,
    ``xLocationId`` and ``xLocationName`` keep the real data intact.
    """
    is_location = visit.stop_type == 'location'
    location = visit.stop_location_id
    return {
        'id': sid(visit.id),
        'routeId': sid(visit.plan_id.id) if visit.plan_id else '',
        'customerId': sid(visit.partner_id.id) if visit.partner_id else '',
        'customerName': (s(location.display_name) if is_location
                         else s(visit.partner_id.display_name)),
        'customerCode': s(location.code) if is_location else s(visit.partner_id.ref),
        'area': '',
        'sequence': i(visit.sequence),
        'visitStatus': VISIT_STATUS.get(visit.state, 'PLANNED'),
        'plannedTime': None,
        'checkInTime': opt(dt(visit.check_in_datetime)),
        'checkOutTime': opt(dt(visit.check_out_datetime)),
        # Gated on whether the event happened, NOT on whether the number is
        # zero. An Odoo Float has no "unset" state, so `value or None` would
        # report a genuine 0.0 coordinate - or a same-minute visit - as "not
        # recorded". The timestamp is the unambiguous signal.
        'checkInLat': f(visit.check_in_latitude) if visit.check_in_datetime else None,
        'checkInLng': f(visit.check_in_longitude) if visit.check_in_datetime else None,
        'checkOutLat': f(visit.check_out_latitude) if visit.check_out_datetime else None,
        'checkOutLng': f(visit.check_out_longitude) if visit.check_out_datetime else None,
        'visitDuration': f(visit.duration_minutes) if visit.check_out_datetime else None,
        'skipReason': opt(visit.skip_reason),
        'xStopType': s(visit.stop_type),
        'xLocationId': sid(location.id) if location else '',
        'xLocationName': s(location.display_name) if location else '',
        'xIsAdhoc': b(visit.is_adhoc),
        'xCity': s(visit.stop_city),
    }


def route(plan, with_stops=True):
    """A **visit plan** as a contract ``Route``.

    The contract's Route carries a ``date`` and a stop list, which is our
    ``van.sales.visit.plan`` - one day of one route - rather than our
    ``van.sales.route`` master. The plan's id is therefore the ``routeId`` the
    app sees; ``xRouteMasterId`` exposes the underlying route.
    """
    visits = plan.visit_ids.sorted(lambda v: (v.sequence, v.id))
    payload = {
        'id': sid(plan.id),
        'name': s(plan.route_id.display_name or plan.name),
        'salesmanId': sid(plan.salesman_user_id.id)
                      if plan.salesman_user_id else '',
        'date': dt(plan.date),
        'totalStops': i(len(visits)),
        'completedStops': i(len(visits.filtered(lambda v: v.state == 'done'))),
        'skippedStops': i(len(visits.filtered(lambda v: v.state == 'skipped'))),
        'xRouteMasterId': sid(plan.route_id.id) if plan.route_id else '',
        'xRouteType': s(plan.route_id.route_type),
        'xVanId': sid(plan.van_id.id) if plan.van_id else '',
        'xState': s(plan.state),
    }
    payload['stops'] = [route_stop(v) for v in visits] if with_stops else []
    return payload


# =============================================================================
# GRN
# =============================================================================

def grn_line(move):
    expected = move.product_uom_qty
    received = move.quantity
    return {
        'id': sid(move.id),
        'productId': sid(move.product_id.id) if move.product_id else '',
        'productCode': s(move.product_id.default_code),
        'productName': s(move.product_id.display_name),
        'expectedQty': f(expected),
        'receivedQty': f(received),
        'difference': f(received - expected),
        'reason': None,          # ours is per picking, not per line
        'photoUrl': None,
    }


def grn(picking, with_lines=True):
    payload = {
        'id': sid(picking.id),
        'clientUuid': '',
        'transferNumber': s(picking.name),
        'sourceWarehouse': s(picking.location_id.complete_name),
        'destinationVan': s(picking.location_dest_id.complete_name),
        'vanId': sid(picking.van_id.id) if picking.van_id else '',
        'date': dt(picking.scheduled_date),
        'status': grn_status(picking),
        'syncStatus': 'SYNCED',
        'notes': opt(picking.van_discrepancy_note),
        'createdAt': dt(picking.create_date),
        'xOperation': s(picking.van_operation),
        'xState': s(picking.state),
        'xHasDiscrepancy': b(picking.van_has_discrepancy),
    }
    if with_lines:
        payload['lines'] = [grn_line(m) for m in picking.move_ids]
    return payload


# =============================================================================
# NOTIFICATIONS
# =============================================================================

def notification(record):
    import json as _json
    data = {}
    if record.data:
        try:
            parsed = _json.loads(record.data)
            if isinstance(parsed, dict):
                data = parsed
        except (ValueError, TypeError):
            data = {}
    if record.res_model:
        data.setdefault('resModel', s(record.res_model))
        data.setdefault('resId', sid(record.res_id))
    return {
        'id': sid(record.id),
        'type': NOTIFICATION_TYPE.get(record.notification_type, 'ANNOUNCEMENT'),
        'title': s(record.title),
        'message': s(record.body),
        'date': dt(record.create_date),
        'read': b(record.is_read),
        'data': data,
        'nativeType': s(record.notification_type),
    }


# =============================================================================
# STOCK
# =============================================================================

def stock_item(product_record, van, quantity):
    """Current van stock in the contract's ``StockItem`` shape.

    **Known limitation, stated rather than papered over:** the contract's
    StockItem is a *day ledger* - opening, loaded, sold, returned, expected,
    actual. That ledger is ``van.sales.reconciliation.line``, which has no API
    yet. What is real here is ``expectedClosing`` (what the van is carrying
    right now) and the product identity. The ledger fields are zero and
    ``ledgerAvailable`` is **false**, so the app can gate that section of the
    screen instead of displaying four numbers that were never computed.
    """
    return {
        'id': '%s-%s' % (sid(van.id), sid(product_record.id)),
        'productId': sid(product_record.id),
        'productCode': s(product_record.default_code),
        'productName': s(product_record.display_name),
        'vanId': sid(van.id),
        'openingStock': 0.0,
        'loadedQty': 0.0,
        'soldQty': 0.0,
        'returnedQty': 0.0,
        'focQty': 0.0,
        'expectedClosing': f(quantity),
        'actualClosing': None,
        'unit': s(product_record.uom_id.display_name)
                if product_record.uom_id else '',
        'lowStockThreshold': 0.0,
        'ledgerAvailable': False,
    }


# =============================================================================
# SETTINGS
# =============================================================================

PARAM_TAX_LABEL = 'van_sales.tax_label'
PARAM_TAX_INCLUDED = 'van_sales.tax_included_by_default'


def company_settings(company):
    """Company-wide display settings.

    ``taxLabel`` and ``taxIncludedByDefault`` are **configuration
    parameters**, not guesses: what a jurisdiction calls its tax is a business
    fact nobody has told us yet, and deriving it from the country code would
    be exactly the kind of assumption that reaches a customer's invoice.
    Set them in Settings -> Technical -> System Parameters.
    """
    params = request.env['ir.config_parameter'].sudo()
    currency = company.currency_id
    return {
        'currencyCode': s(currency.name),
        'currencySymbol': s(currency.symbol),
        'currencyDecimals': i(currency.decimal_places),
        'currencyPosition': s(currency.position) or 'before',
        'taxLabel': s(params.get_param(PARAM_TAX_LABEL, 'Tax')),
        'taxIncludedByDefault': str(
            params.get_param(PARAM_TAX_INCLUDED, 'False')
        ).strip().lower() in ('1', 'true', 'yes'),
        'companyName': s(company.name),
        'companyPhone': opt(company.phone),
        'companyEmail': opt(company.email),
        'companyAddress': ', '.join(part for part in (
            company.street, company.street2, company.city,
            company.zip, company.country_id.name) if part),
        'companyVat': opt(company.vat),
    }
