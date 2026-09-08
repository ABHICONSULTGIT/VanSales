# Part of the Van Sales project.

from odoo import _, http
from odoo.http import request

from .base import (ErrCode, current_device, current_user, error_response,
                   get_json_body, success_response, token_required,
                   _b, _i, _m2o, _s)


def _device_payload(device):
    return {
        'id': _i(device.id),
        'device_uuid': _s(device.device_uuid),
        'device_number': _s(device.device_number),
        'active': _b(device.active),
        'van': _m2o(device.van_id),
        'user': _m2o(device.user_id),
        'company': _m2o(device.company_id),
        'last_sync_at': _s(device.last_sync_at),
        'registered_at': _s(device.registered_at),
    }


class VanSalesDeviceController(http.Controller):

    @http.route('/api/v1/device/register', type='http', auth='public',
                methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    def register(self, **kw):
        """Register this handset, or refresh it if it is already known.

        Returns a **device_number** issued once and never re-issued. The app
        prefixes its offline document references with it, so two handsets can
        never generate the same reference while both are out of signal - the
        same mechanism Odoo's Point of Sale uses.
        """
        body = get_json_body()
        device_uuid = (body.get('device_uuid')
                       or request.httprequest.headers.get('X-Device-ID', '')
                       or '').strip()
        if not device_uuid:
            return error_response(
                _("A device_uuid is required to register."),
                status=400, code=ErrCode.VALIDATION)

        device = request.env['van.sales.device'].sudo().register(
            current_user(), device_uuid, {
                'device_type': body.get('device_type'),
                'device_model': body.get('device_model'),
                'os_version': body.get('os_version'),
                'app_version': body.get('app_version'),
                'fcm_token': body.get('fcm_token'),
            })
        if not device.van_id:
            return success_response(
                data=_device_payload(device),
                message=_("Registered, but no van is assigned to this "
                          "salesman yet. Syncing will not work until the "
                          "office assigns one."))
        return success_response(
            data=_device_payload(device), message=_("Device registered."))

    @http.route('/api/v1/device/heartbeat', type='http', auth='public',
                methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    def heartbeat(self, **kw):
        device = current_device()
        if not device:
            return error_response(
                _("Unknown device. Register it first."),
                status=403, code=ErrCode.DEVICE_UNKNOWN)
        body = get_json_body()
        device.touch(app_version=body.get('app_version'))
        return success_response(data=_device_payload(device))

    @http.route('/api/v1/device/fcm-token', type='http', auth='public',
                methods=['POST', 'PUT', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    def fcm_token(self, **kw):
        device = current_device()
        if not device:
            return error_response(
                _("Unknown device. Register it first."),
                status=403, code=ErrCode.DEVICE_UNKNOWN)
        token = (get_json_body().get('fcm_token') or '').strip()
        if not token:
            return error_response(
                _("fcm_token is required."),
                status=400, code=ErrCode.VALIDATION)
        device.sudo().write({'fcm_token': token})
        return success_response(message=_("Push token saved."))
