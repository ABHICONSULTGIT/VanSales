# Part of the Van Sales project.
"""The offline sync engine: pull, push, and idempotency.

Kept in a model rather than the controller so it is overridable, reusable from
a cron or a test, and thin at the HTTP edge.

The whole design answers one fact about van sales: the connection drops
constantly, so the app **will** re-send batches whose reply it never received.
Every pushed record therefore carries a UUID the device generated before the
record existed, and van.sales.sync.log records it. A retry is recognised and
its original result replayed, instead of creating a second order.
"""

import json
import logging
import time

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

# Order matters: each model's domain receives everything selected so far, so
# route lines can filter on their routes, invoices on the customers actually
# being sent, and so on.
LOAD_ORDER = [
    'res.company',
    'res.users',
    'fleet.vehicle',
    'van.sales.route',
    'van.sales.route.line',
    'van.sales.stop.location',
    'res.partner',
    'uom.uom',
    'product.product',
    'product.category',
    'account.tax',
    'product.pricelist',
    'product.pricelist.item',
    'stock.quant',
    'van.sales.visit.plan',
    'van.sales.visit',
    'account.move',
    'sale.order',
    'sale.order.line',
    'van.sales.collection',
    'van.sales.collection.line',
    'stock.picking',
    'stock.move',
]

# Models the device may ask us to reconcile its local ids against.
CLEANUP_MODELS = [
    'res.partner', 'product.product', 'van.sales.route.line',
    'van.sales.stop.location', 'account.move', 'stock.picking',
]

PUSHABLE_MODELS = (
    'van.sales.visit', 'sale.order', 'van.sales.collection', 'stock.picking',
)


class VanSalesSync(models.AbstractModel):
    _name = 'van.sales.sync'
    _description = "Van Sales Sync Engine"

    # =================================================================
    # PULL
    # =================================================================
    @api.model
    def server_time(self):
        """Transaction start, not wall clock.

        The watermark has to be consistent with the data in this very
        response: using ``now()`` could skip a record written a millisecond
        after the query but before the reply.
        """
        return self.env.cr.now()

    @api.model
    def load(self, device, watermark=None, models_to_load=None):
        """Return ``{model: [records]}`` for this device."""
        response = {}
        loader_env = self.env
        if watermark:
            loader_env = self.env(context=dict(
                self.env.context, van_sales_watermark=watermark))
        for model_name in LOAD_ORDER:
            if models_to_load and model_name not in models_to_load:
                continue
            if model_name not in self.env:
                continue
            Model = loader_env[model_name]
            if not hasattr(Model, '_van_load_search_read'):
                continue
            try:
                response[model_name] = Model._van_load_search_read(response, device)
            except AccessError as err:
                _logger.info(
                    "Van Sales sync: skipping %s (%s)", model_name, err)
                response[model_name] = []
        return response

    @api.model
    def schema(self, device):
        """Field list per model, so the client can build its local store."""
        result = {}
        for model_name in LOAD_ORDER:
            if model_name not in self.env:
                continue
            Model = self.env[model_name]
            if not hasattr(Model, '_van_load_fields'):
                continue
            names = Model._van_load_fields(device)
            if not names:
                continue
            described = {}
            for name in names:
                field = Model._fields.get(name)
                if not field:
                    continue
                described[name] = {
                    'type': field.type,
                    'relation': getattr(field, 'comodel_name', None) or '',
                    'required': bool(field.required),
                }
            result[model_name] = described
        return result

    @api.model
    def filter_local(self, device, ids_by_model):
        """Which of the ids the device holds it should drop.

        Archived records still exist, so ``exists()`` alone is not enough - the
        device would keep offering a customer the office retired.
        """
        result = {}
        for model_name, ids in (ids_by_model or {}).items():
            if model_name not in CLEANUP_MODELS or model_name not in self.env:
                continue
            ids = [int(i) for i in ids if str(i).lstrip('-').isdigit()]
            if not ids:
                result[model_name] = []
                continue
            records = self.env[model_name].sudo().with_context(
                active_test=False).browse(ids).exists()
            gone = set(ids) - set(records.ids)
            if hasattr(records, '_van_irrelevant_ids'):
                gone.update(records._van_irrelevant_ids(device))
            result[model_name] = sorted(gone)
        return result

    # =================================================================
    # PUSH
    # =================================================================
    @api.model
    def push(self, device, batch_uuid, records):
        """Process a batch. One savepoint per record.

        Per record, never per batch: one bad order must not throw away the
        eleven good ones behind it, because the device has no way to tell them
        apart and would re-send everything.
        """
        results = []
        for payload in records or []:
            results.append(self._push_one(device, batch_uuid, payload))
        return results

    @api.model
    def _push_one(self, device, batch_uuid, payload):
        started = time.time()
        client_uuid = (payload or {}).get('client_uuid') or ''
        model_name = (payload or {}).get('model') or ''

        if not client_uuid:
            return self._result(
                client_uuid, 'rejected', model_name,
                code='VALIDATION_ERROR',
                message=_("Every pushed record needs a client_uuid."))
        if model_name not in PUSHABLE_MODELS:
            return self._log_and_result(
                device, batch_uuid, payload, 'rejected',
                code='UNSUPPORTED_MODEL',
                message=_("%s cannot be pushed from the app.", model_name),
                started=started)

        # Idempotency: has this exact record already been dealt with?
        previous = self.env['van.sales.sync.log'].find_processed(client_uuid)
        if previous:
            return self._result(
                client_uuid, 'duplicate', previous.res_model,
                res_id=previous.res_id, name=previous.record_ref,
                message=_("Already processed."))

        handler = getattr(self, '_push_%s' % model_name.replace('.', '_'), None)
        if handler is None:
            return self._log_and_result(
                device, batch_uuid, payload, 'rejected',
                code='UNSUPPORTED_MODEL',
                message=_("No handler for %s.", model_name), started=started)

        try:
            with self.env.cr.savepoint():
                record = handler(device, payload)
            return self._log_and_result(
                device, batch_uuid, payload, 'success',
                record=record, started=started)
        except (UserError, ValidationError) as err:
            # The savepoint rolled the DB back; the ORM cache did not follow,
            # so drop it before touching anything else.
            self.env.invalidate_all()
            return self._log_and_result(
                device, batch_uuid, payload, 'rejected',
                code=self._classify(err), message=str(err), started=started)
        except Exception as err:                         # noqa: BLE001
            self.env.invalidate_all()
            _logger.exception(
                "Van Sales push failed for %s (%s)", model_name, client_uuid)
            return self._log_and_result(
                device, batch_uuid, payload, 'error',
                code='SERVER_ERROR', message=str(err), started=started)

    @api.model
    def _classify(self, error):
        """Best-effort mapping of a business refusal to a stable code."""
        text = str(error).lower()
        if 'credit limit' in text:
            return 'CREDIT_LIMIT_EXCEEDED'
        if 'not carrying enough' in text or 'insufficient' in text:
            return 'STOCK_INSUFFICIENT'
        if 'already' in text and 'paid' in text:
            return 'INVOICE_ALREADY_PAID'
        return 'VALIDATION_ERROR'

    @api.model
    def _result(self, client_uuid, status, model_name, res_id=0, name='',
                code=None, message=None, extra=None):
        payload = {
            'client_uuid': client_uuid,
            'status': status,
            'model': model_name or '',
            'id': res_id or 0,
            'name': name or '',
        }
        if code:
            payload['code'] = code
        if message:
            payload['message'] = message
        if extra:
            payload['extra'] = extra
        return payload

    @api.model
    def _log_and_result(self, device, batch_uuid, payload, status, record=None,
                        code=None, message=None, started=None):
        client_uuid = payload.get('client_uuid') or ''
        model_name = payload.get('model') or ''
        res_id = record.id if record else 0
        name = record.display_name if record else ''
        try:
            self.env['van.sales.sync.log'].sudo().create({
                'batch_uuid': batch_uuid or '',
                'client_uuid': client_uuid,
                'device_id': device.id,
                'user_id': self.env.user.id,
                'res_model': model_name,
                'res_id': res_id,
                'record_ref': name,
                'status': status,
                'error_code': code or '',
                'error_message': message or '',
                'payload': json.dumps(payload, default=str)[:20000],
                'captured_at': payload.get('captured_at') or False,
                'duration_ms': round((time.time() - started) * 1000, 2)
                if started else 0.0,
            })
        except Exception:                                # noqa: BLE001
            _logger.exception("Van Sales: could not write the sync log")
        return self._result(client_uuid, status, model_name, res_id=res_id,
                            name=name, code=code, message=message,
                            extra=payload.get('_extra'))

    # -----------------------------------------------------------------
    # Handlers
    # -----------------------------------------------------------------
    @api.model
    def _push_van_sales_visit(self, device, payload):
        data = payload.get('data') or {}
        operation = payload.get('op') or 'create'
        Visit = self.env['van.sales.visit']
        captured = payload.get('captured_at') or False
        position = {}
        if data.get('latitude') is not None:
            position['van_sales_latitude'] = float(data['latitude'])
        if data.get('longitude') is not None:
            position['van_sales_longitude'] = float(data['longitude'])

        if operation == 'create':
            plan = self.env['van.sales.visit.plan'].browse(
                int(data.get('plan_id') or 0)).exists()
            if not plan:
                raise UserError(_("The visit plan no longer exists."))
            visit = Visit.create({
                'plan_id': plan.id,
                'stop_type': data.get('stop_type') or 'customer',
                'partner_id': data.get('partner_id') or False,
                'stop_location_id': data.get('stop_location_id') or False,
                'sequence': data.get('sequence') or 99,
                'is_adhoc': True,
                'adhoc_reason': data.get('adhoc_reason') or '',
                'van_client_uuid': payload.get('client_uuid'),
            })
            return visit

        visit = Visit.browse(int(data.get('visit_id') or 0)).exists()
        if not visit:
            raise UserError(_("This stop no longer exists."))
        if not visit.van_client_uuid:
            visit.van_client_uuid = payload.get('client_uuid')

        if operation == 'check_in':
            visit.with_context(**position).action_check_in()
            if captured:
                visit.sudo().write({'check_in_datetime': captured})
        elif operation == 'check_out':
            visit.with_context(**position).action_check_out()
            if captured:
                visit.sudo().write({'check_out_datetime': captured})
        elif operation == 'skip':
            visit.skip_reason = data.get('skip_reason') or ''
            visit.action_skip()
        else:
            raise UserError(_("Unknown visit operation '%s'.", operation))
        return visit

    @api.model
    def _push_sale_order(self, device, payload):
        data = payload.get('data') or {}
        van = device.van_id
        partner_id = int(data.get('partner_id') or 0)
        if not partner_id:
            raise UserError(_("A sale needs a customer."))

        lines = []
        for line in data.get('lines') or []:
            product_id = int(line.get('product_id') or 0)
            if not product_id:
                continue
            values = {
                'product_id': product_id,
                'product_uom_qty': float(line.get('quantity') or 0.0),
            }
            if line.get('price_unit') is not None:
                values['price_unit'] = float(line['price_unit'])
            if line.get('discount') is not None:
                values['discount'] = float(line['discount'])
            if line.get('uom_id'):
                values['product_uom_id'] = int(line['uom_id'])
            lines.append((0, 0, values))
        if not lines:
            raise UserError(_("A sale needs at least one line."))

        order = self.env['sale.order'].create({
            'partner_id': partner_id,
            'van_id': van.id,
            'van_route_id': int(data.get('route_id') or 0) or False,
            'van_visit_id': int(data.get('visit_id') or 0) or False,
            'van_client_uuid': payload.get('client_uuid'),
            'van_captured_datetime': payload.get('captured_at') or False,
            'order_line': lines,
        })

        # Typed pre-checks before confirming. The model raises its own
        # UserError as the backstop, but a sentence cannot be matched on by
        # the app - §6.2 asks for errors that map to user-facing messages.
        self._precheck_van_stock(order)
        self._precheck_credit(order)

        if data.get('confirm'):
            order.action_confirm()
        if data.get('deliver'):
            self._validate_deliveries(order)
        if data.get('invoice') and order.state == 'sale':
            invoices = order._create_invoices()
            if invoices:
                invoices.write({
                    'van_captured_datetime': payload.get('captured_at') or False,
                })
                invoices.action_post()
                payload['_extra'] = {
                    'invoice_ids': invoices.ids,
                    'invoice_names': invoices.mapped('name'),
                }
        return order

    @api.model
    def _precheck_van_stock(self, order):
        van = order.van_id
        if not van or not van.van_location_id:
            return
        available = van._van_sales_available_quantities()
        shortages = []
        for product, needed in order._van_sales_required_quantities().items():
            on_van = available.get(product.id, 0.0)
            if product.uom_id.compare(needed, on_van) <= 0:
                continue
            if (product.van_sale_stock_policy_effective or 'warn') != 'block':
                continue
            shortages.append(_(
                "%(product)s: %(needed).2f needed, %(available).2f on the van",
                product=product.display_name, needed=needed, available=on_van))
        if shortages:
            raise UserError(_(
                "The van is not carrying enough stock:\n%s",
                "\n".join(shortages)))

    @api.model
    def _precheck_credit(self, order):
        company = order.company_id or self.env.company
        if (company.van_sale_credit_policy or 'warn') != 'block':
            return
        if not company.account_use_credit_limit:
            return
        rate = order.currency_rate or 1.0
        warning = self.env['account.move']._build_credit_warning_message(
            order.sudo(), current_amount=(order.amount_total / rate))
        if warning:
            raise UserError(warning)

    @api.model
    def _validate_deliveries(self, order):
        """Hand the goods over: the van sale is delivered as it is made."""
        pickings = order.picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel'))
        for picking in pickings:
            picking.action_assign()
            for move in picking.move_ids:
                if move.state in ('done', 'cancel'):
                    continue
                move.quantity = move.product_uom_qty
                move.picked = True
            picking.with_context(
                skip_backorder=True,
                picking_ids_not_to_backorder=picking.ids,
            ).button_validate()

    @api.model
    def _push_van_sales_collection(self, device, payload):
        data = payload.get('data') or {}
        lines = []
        for line in data.get('lines') or []:
            move_id = int(line.get('invoice_id') or 0)
            amount = float(line.get('amount') or 0.0)
            if move_id and amount:
                lines.append((0, 0, {'move_id': move_id, 'amount': amount}))
        if not lines:
            raise UserError(_("A collection needs at least one allocation."))
        journal_id = int(data.get('journal_id') or 0) or device.van_id.cash_journal_id.id
        if not journal_id:
            raise UserError(_(
                "No cash journal is set on van %s.", device.van_id.display_name))
        collection = self.env['van.sales.collection'].create({
            'partner_id': int(data.get('partner_id') or 0),
            'van_id': device.van_id.id,
            'visit_id': int(data.get('visit_id') or 0) or False,
            'journal_id': journal_id,
            'date': data.get('date') or fields.Date.context_today(self),
            'memo': data.get('memo') or '',
            'van_client_uuid': payload.get('client_uuid'),
            'line_ids': lines,
        })
        if data.get('post', True):
            collection.action_post()
            payload['_extra'] = {'payment_ids': collection.payment_ids.ids}
        return collection

    @api.model
    def _push_stock_picking(self, device, payload):
        """Confirm a van load in the field - the GRN of §5.9."""
        data = payload.get('data') or {}
        picking = self.env['stock.picking'].browse(
            int(data.get('picking_id') or 0)).exists()
        if not picking:
            raise UserError(_("This transfer no longer exists."))
        if picking.van_id != device.van_id:
            raise UserError(_("This transfer belongs to another van."))
        if picking.state in ('done', 'cancel'):
            raise UserError(_(
                "Transfer %(name)s is already %(state)s.",
                name=picking.name, state=picking.state))

        picking.action_assign()
        by_move = {int(row.get('move_id') or 0): row
                   for row in data.get('moves') or []}
        for move in picking.move_ids:
            if move.state in ('done', 'cancel'):
                continue
            row = by_move.get(move.id)
            move.quantity = (float(row.get('quantity'))
                             if row and row.get('quantity') is not None
                             else move.product_uom_qty)
            move.picked = True
        if data.get('discrepancy_note'):
            picking.van_discrepancy_note = data['discrepancy_note']
        picking.with_context(
            skip_backorder=True,
            picking_ids_not_to_backorder=picking.ids,
        ).button_validate()
        return picking
