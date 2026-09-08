# Part of the Van Sales project.

from odoo import _, http
from odoo.http import request

from .base import (ErrCode, current_device, error_response, get_json_body,
                   success_response, token_required, device_required, _s)


class VanSalesSyncController(http.Controller):
    """Pull and push.

    A note on the watermark, because getting it wrong loses data silently:
    **the client owns it**. Each response carries ``server_time``; the app
    stores it and sends it back as ``since`` on the next pull. The server also
    records it on the device, but only as a diagnostic - if the server advanced
    the watermark itself and the app then failed to apply the response, the
    records in between would never be sent again.
    """

    @http.route('/api/v1/sync/bootstrap', type='http', auth='public',
                methods=['POST', 'GET', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    @device_required
    def bootstrap(self, **kw):
        device = current_device()
        Sync = request.env['van.sales.sync']
        server_time = Sync.server_time()
        data = Sync.load(device, watermark=None)
        device.sudo().write({'last_sync_at': server_time})
        return success_response(data={
            'server_time': _s(server_time),
            'schema': Sync.schema(device),
            'records': data,
            'counts': {model: len(rows) for model, rows in data.items()},
        }, message=_("Full dataset."))

    @http.route('/api/v1/sync/pull', type='http', auth='public',
                methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    @device_required
    def pull(self, **kw):
        device = current_device()
        body = get_json_body()
        since = body.get('since') or None
        Sync = request.env['van.sales.sync']
        server_time = Sync.server_time()
        data = Sync.load(device, watermark=since,
                         models_to_load=body.get('models') or None)
        device.sudo().write({'last_sync_at': server_time})
        return success_response(data={
            'server_time': _s(server_time),
            'since': _s(since or ''),
            'full': not bool(since),
            'records': data,
            'counts': {model: len(rows) for model, rows in data.items()},
        })

    @http.route('/api/v1/sync/filter-local', type='http', auth='public',
                methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    @device_required
    def filter_local(self, **kw):
        """Tell the device which of the ids it holds it should drop.

        There is no tombstone table: the device says what it has, and the
        server answers what is gone or archived. Simpler, and self-healing
        after any missed sync.
        """
        body = get_json_body()
        removed = request.env['van.sales.sync'].filter_local(
            current_device(), body.get('ids') or {})
        return success_response(data={'remove': removed})

    @http.route('/api/v1/sync/push', type='http', auth='public',
                methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    @device_required
    def push(self, **kw):
        device = current_device()
        body = get_json_body()
        records = body.get('records') or []
        if not isinstance(records, list):
            return error_response(
                _("'records' must be a list."),
                status=400, code=ErrCode.VALIDATION)
        if len(records) > 200:
            return error_response(
                _("Send at most 200 records per batch."),
                status=400, code=ErrCode.VALIDATION)

        Sync = request.env['van.sales.sync']
        results = Sync.push(device, body.get('batch_uuid') or '', records)
        accepted = sum(1 for r in results if r['status'] == 'success')
        device.sudo().write({
            'push_count': device.push_count + accepted,
            'last_seen_at': request.env.cr.now(),
        })
        return success_response(data={
            'batch_uuid': body.get('batch_uuid') or '',
            'server_time': _s(Sync.server_time()),
            'results': results,
            'summary': {
                'total': len(results),
                'success': accepted,
                'duplicate': sum(1 for r in results if r['status'] == 'duplicate'),
                'rejected': sum(1 for r in results if r['status'] == 'rejected'),
                'error': sum(1 for r in results if r['status'] == 'error'),
            },
        })
