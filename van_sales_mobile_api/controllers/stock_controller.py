# Part of the Van Sales project.

from odoo import Command, http
from odoo.http import request

from .base import (
    API_PREFIX, ApiError, as_float, as_int, body, date_param, datetime_domain,
    fmt_date, fmt_datetime, get_own, int_param, lines_payload, me, my_van, ok,
    paginate, param, ref, token_required,
)

TYPE_TO_OPERATION = {'load': 'load', 'return': 'unload', 'delivery': 'delivery'}
OPERATION_TO_TYPE = {v: k for k, v in TYPE_TO_OPERATION.items()}
OPEN_STATES = ('draft', 'waiting', 'confirmed', 'assigned')


def transfer_item(picking):
    return {
        'id': picking.id,
        'name': picking.name,
        'type': OPERATION_TO_TYPE.get(picking.van_operation, 'other'),
        'state': picking.state,
        'date': fmt_datetime(picking.date_done or picking.scheduled_date),
        'source': picking.location_id.complete_name,
        'destination': picking.location_dest_id.complete_name,
        'origin': picking.origin or None,
    }


def transfer_detail(picking):
    data = transfer_item(picking)
    done = picking.state == 'done'
    data['lines'] = [{
        'product_id': move.product_id.id,
        'product': move.product_id.name,
        'uom': move.product_uom.name,
        'requested_qty': move.product_uom_qty,
        'done_qty': move.quantity if done else 0.0,
    } for move in picking.move_ids]
    return data


def count_detail(count):
    return {
        'id': count.id,
        'name': count.name,
        'date': fmt_date(count.date),
        'state': count.state,
        'note': count.note or None,
        'lines': [{
            'product_id': line.product_id.id,
            'product': line.product_id.name,
            'uom': line.product_uom_id.name,
            'system_qty': line.expected_qty,
            'counted_qty': line.counted_qty,
            'difference': line.difference_qty,
        } for line in count.line_ids],
    }


def count_item(count):
    return {
        'id': count.id,
        'name': count.name,
        'date': fmt_date(count.date),
        'state': count.state,
        'products': len(count.line_ids),
        'differences': len(count.line_ids.filtered('difference_qty')),
    }


def my_transfer(picking_id, van):
    return get_own('stock.picking', picking_id, [('van_id', '=', van.id)])


def request_transfer(van, source, destination, data, label):
    """A confirmed internal transfer for the warehouse to validate (D4)."""
    warehouse, picking_type = van._van_sales_internal_picking_type()
    lines = lines_payload(data)
    for product, _qty in lines:
        if not product.is_storable:
            raise ApiError("%s is not a stocked product." % product.display_name)
    picking = request.env['stock.picking'].create({
        'picking_type_id': picking_type.id,
        'location_id': source.id,
        'location_dest_id': destination.id,
        'origin': "%s - %s (app)" % (label, van.display_name),
        'note': data.get('note') or False,
        'move_ids': [Command.create({
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': source.id,
            'location_dest_id': destination.id,
        }) for product, qty in lines],
    })
    picking.action_confirm()
    return picking


class VanSalesStockController(http.Controller):

    # ------------------------------------------------------------------
    # Transfers: loads, returns, deliveries
    # ------------------------------------------------------------------
    @http.route(API_PREFIX + '/stock/transfers', type='http', auth='public',
                methods=['GET'], csrf=False, cors='*')
    @token_required
    def transfers(self, **kw):
        van = my_van()
        domain = [('van_id', '=', van.id)]
        kind = param('type')
        if kind:
            if kind not in TYPE_TO_OPERATION:
                raise ApiError("'type' must be one of: load, return, delivery.")
            domain.append(('van_operation', '=', TYPE_TO_OPERATION[kind]))
        state = param('state')
        if state:
            domain.append(('state', '=', state))
        domain += datetime_domain('scheduled_date', date_param('date_from'),
                                  date_param('date_to'))
        pickings, page = paginate(request.env['stock.picking'], domain,
                                  order='scheduled_date desc, id desc')
        return ok([transfer_item(p) for p in pickings], pagination=page)

    @http.route(API_PREFIX + '/stock/transfers/<int:picking_id>', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    @token_required
    def transfer(self, picking_id, **kw):
        return ok(transfer_detail(my_transfer(picking_id, my_van())))

    @http.route(API_PREFIX + '/stock/load-requests', type='http',
                auth='public', methods=['POST'], csrf=False, cors='*')
    @token_required
    def load_request(self, **kw):
        van = my_van()
        warehouse, _type = van._van_sales_internal_picking_type()
        picking = request_transfer(van, warehouse.lot_stock_id,
                                   van.van_location_id, body(), "Load request")
        return ok(transfer_detail(picking),
                  "Load requested. The warehouse will validate it.", status=201)

    @http.route(API_PREFIX + '/stock/return-requests', type='http',
                auth='public', methods=['POST'], csrf=False, cors='*')
    @token_required
    def return_request(self, **kw):
        van = my_van()
        data = body()
        on_van = van._van_sales_available_quantities()
        wanted = {}
        for product, qty in lines_payload(data):
            wanted[product] = wanted.get(product, 0.0) + qty
        for product, qty in wanted.items():
            available = on_van.get(product.id, 0.0)
            if product.uom_id.compare(qty, available) > 0:
                raise ApiError("%s: %s to return but only %s on the van."
                               % (product.display_name, qty, available))
        warehouse, _type = van._van_sales_internal_picking_type()
        picking = request_transfer(van, van.van_location_id,
                                   warehouse.lot_stock_id, data,
                                   "Return request")
        return ok(transfer_detail(picking),
                  "Return requested. The warehouse will validate it on "
                  "receipt.", status=201)

    @http.route(API_PREFIX + '/stock/transfers/<int:picking_id>/cancel',
                type='http', auth='public', methods=['POST'], csrf=False,
                cors='*')
    @token_required
    def cancel_request(self, picking_id, **kw):
        picking = my_transfer(picking_id, my_van())
        if picking.van_operation not in ('load', 'unload'):
            raise ApiError("Only load and return requests can be cancelled "
                           "from the app.", 409)
        if picking.create_uid != me():
            raise ApiError("Only requests you raised can be cancelled.", 403)
        if picking.state not in OPEN_STATES:
            raise ApiError("This transfer is already %s." % picking.state, 409)
        picking.action_cancel()
        return ok(transfer_detail(picking), "Request cancelled.")

    @http.route(API_PREFIX + '/stock/movements', type='http', auth='public',
                methods=['GET'], csrf=False, cors='*')
    @token_required
    def movements(self, **kw):
        van = my_van()
        locations = request.env['stock.location'].search(
            [('id', 'child_of', van.van_location_id.id)])
        domain = [('state', '=', 'done'), '|',
                  ('location_id', 'in', locations.ids),
                  ('location_dest_id', 'in', locations.ids)]
        product_id = int_param('product_id')
        if product_id:
            domain.append(('product_id', '=', product_id))
        domain += datetime_domain('date', date_param('date_from'),
                                  date_param('date_to'))
        move_lines, page = paginate(request.env['stock.move.line'], domain,
                                    order='date desc, id desc')
        result = []
        for line in move_lines:
            incoming = line.location_dest_id in locations
            picking = line.picking_id
            if picking:
                kind = OPERATION_TO_TYPE.get(picking.van_operation, 'other')
            elif line.move_id.is_inventory:
                kind = 'adjustment'
            else:
                kind = 'other'
            result.append({
                'id': line.id,
                'date': fmt_datetime(line.date),
                'product': ref(line.product_id, 'name'),
                'qty': line.quantity,
                'uom': line.product_uom_id.name,
                'direction': 'in' if incoming else 'out',
                'type': kind,
                'reference': picking.name or line.reference or None,
            })
        return ok(result, pagination=page)

    # ------------------------------------------------------------------
    # Stock counts (reconciliation) - decision D4
    # ------------------------------------------------------------------
    @http.route(API_PREFIX + '/stock/counts', type='http', auth='public',
                methods=['GET'], csrf=False, cors='*')
    @token_required
    def counts(self, **kw):
        van = my_van()
        counts, page = paginate(request.env['van.sales.reconciliation'],
                                [('van_id', '=', van.id)],
                                order='date desc, id desc')
        return ok([count_item(c) for c in counts], pagination=page)

    @http.route(API_PREFIX + '/stock/counts/<int:count_id>', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    @token_required
    def count(self, count_id, **kw):
        van = my_van()
        return ok(count_detail(get_own('van.sales.reconciliation', count_id,
                                       [('van_id', '=', van.id)])))

    @http.route(API_PREFIX + '/stock/counts', type='http', auth='public',
                methods=['POST'], csrf=False, cors='*')
    @token_required
    def start_count(self, **kw):
        van = my_van()
        Count = request.env['van.sales.reconciliation']
        open_count = Count.search([('van_id', '=', van.id),
                                   ('state', '=', 'draft')], limit=1)
        if open_count:
            raise ApiError("Count %s is still open. Finish it first (id %s)."
                           % (open_count.name, open_count.id), 409)
        action = van.action_van_sales_new_reconciliation()
        count = Count.browse(action['res_id'])
        return ok(count_detail(count), "Count started.", status=201)

    @http.route(API_PREFIX + '/stock/counts/<int:count_id>', type='http',
                auth='public', methods=['PUT'], csrf=False, cors='*')
    @token_required
    def update_count(self, count_id, **kw):
        van = my_van()
        count = get_own('van.sales.reconciliation', count_id,
                        [('van_id', '=', van.id)])
        if count.state != 'draft':
            raise ApiError("This count is already applied.", 409)
        data = body()
        if 'lines' not in data and 'note' not in data:
            raise ApiError("Nothing to update.")
        Line = request.env['van.sales.reconciliation.line']
        by_product = {line.product_id.id: line for line in count.line_ids}
        for index, item in enumerate(data.get('lines') or [], start=1):
            if not isinstance(item, dict):
                raise ApiError("Line %s must be an object." % index)
            product_id = as_int(item.get('product_id'), 'product_id')
            counted = as_float(item.get('counted_qty'), 'counted_qty',
                               positive=False)
            line = by_product.get(product_id)
            if line:
                line.counted_qty = counted
                continue
            # Found on the van but unknown to Odoo: add it with system 0.
            product = request.env['product.product'].search(
                [('id', '=', product_id), ('is_storable', '=', True)], limit=1)
            if not product:
                raise ApiError("Line %s: product %s not found."
                               % (index, product_id), 404)
            by_product[product_id] = Line.create({
                'reconciliation_id': count.id, 'product_id': product.id,
                'expected_qty': 0.0, 'counted_qty': counted,
            })
        if 'note' in data:
            count.note = data['note'] or False
        return ok(count_detail(count),
                  "Count saved. The administrator applies it.")
