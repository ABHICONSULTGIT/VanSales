# Part of the Van Sales project.

import logging
import time
from collections import defaultdict

from odoo import _, http
from odoo.exceptions import AccessDenied
from odoo.http import request

from .base import (ErrCode, current_device, current_user, error_response,
                   get_json_body, public_endpoint, success_response,
                   token_required, _b, _i, _m2o, _s)

_logger = logging.getLogger(__name__)

VAN_SALES_GROUP = 'van_sales_base.group_van_sales_user'

# In-memory, per worker. Enough to blunt a stuck retry loop or a casual
# guess; NOT a security control - with four workers the effective ceiling is
# four times this. Put a real limiter in front of Odoo if that matters.
_attempts = defaultdict(list)
RATE_LOGIN = (10, 300)


def _rate_limited(key, limit, window):
    now = time.time()
    _attempts[key] = [t for t in _attempts[key] if now - t < window]
    if len(_attempts[key]) >= limit:
        return True
    _attempts[key].append(now)
    return False


def _user_payload(user, token=None):
    van = request.env['fleet.vehicle'].sudo().search([
        ('is_sales_van', '=', True), ('salesman_user_id', '=', user.id),
    ], limit=1)
    payload = {
        'user': {
            'id': _i(user.id),
            'name': _s(user.name),
            'login': _s(user.login),
            'partner_id': _i(user.partner_id.id),
            'lang': _s(user.van_sales_lang or 'en_US'),
            'company': _m2o(user.company_id),
            'is_supervisor': _b(user.has_group(
                'van_sales_base.group_van_sales_supervisor')),
            'is_manager': _b(user.has_group(
                'van_sales_base.group_van_sales_manager')),
        },
        'van': {
            'id': _i(van.id),
            'name': _s(van.display_name),
            'license_plate': _s(van.license_plate),
            'stock_location_id': _i(van.van_location_id.id),
            'cash_journal_id': _i(van.cash_journal_id.id),
        } if van else None,
    }
    if token:
        payload['token'] = token
    return payload


class VanSalesAuthController(http.Controller):

    @http.route('/api/v1/auth/login', type='http', auth='public',
                methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    @public_endpoint
    def login(self, **kw):
        ip = request.httprequest.remote_addr or 'unknown'
        if _rate_limited('login:%s' % ip, *RATE_LOGIN):
            return error_response(
                _("Too many login attempts. Try again in a few minutes."),
                status=429, code=ErrCode.RATE_LIMITED)

        body = get_json_body()
        login = (body.get('login') or body.get('email') or '').strip()
        password = body.get('password') or ''
        if not login or not password:
            return error_response(
                _("Login and password are required."),
                status=400, code=ErrCode.VALIDATION)

        auth_info = None
        try:
            auth_info = request.session.authenticate(
                request.env,
                {'login': login, 'password': password, 'type': 'password'})
        except AccessDenied:
            auth_info = None
        except Exception:                                # noqa: BLE001
            _logger.info("Van Sales login failed for %s", login, exc_info=True)
            auth_info = None

        uid = auth_info.get('uid') if isinstance(auth_info, dict) else None
        if not uid:
            return error_response(
                _("Invalid credentials."),
                status=401, code=ErrCode.UNAUTHORIZED)

        user = request.env['res.users'].sudo().browse(uid)
        if not user.exists() or not user.active:
            return error_response(
                _("Invalid credentials."),
                status=401, code=ErrCode.UNAUTHORIZED)
        if not user.has_group(VAN_SALES_GROUP):
            return error_response(
                _("This account is not set up for the van sales app."),
                status=403, code=ErrCode.UNAUTHORIZED)

        token = request.env['van.sales.api.token'].sudo().generate_token(
            user.id,
            device_uuid=request.httprequest.headers.get('X-Device-ID', ''),
            ip_address=ip,
            app_version=request.httprequest.headers.get('X-App-Version', ''))
        return success_response(
            data=_user_payload(user, token=token), message=_("Signed in."))

    @http.route('/api/v1/auth/refresh', type='http', auth='public',
                methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    def refresh(self, **kw):
        user = current_user()
        header = request.httprequest.headers.get('Authorization', '')
        Token = request.env['van.sales.api.token'].sudo()
        if header.startswith('Bearer '):
            Token.revoke_token(header[7:].strip())
        token = Token.generate_token(
            user.id,
            device_uuid=request.httprequest.headers.get('X-Device-ID', ''),
            ip_address=request.httprequest.remote_addr or '',
            app_version=request.httprequest.headers.get('X-App-Version', ''))
        return success_response(data={'token': token}, message=_("Token renewed."))

    @http.route('/api/v1/auth/logout', type='http', auth='public',
                methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    def logout(self, **kw):
        body = get_json_body()
        Token = request.env['van.sales.api.token'].sudo()
        if body.get('all_devices'):
            Token.revoke_all_for_user(current_user().id)
        else:
            header = request.httprequest.headers.get('Authorization', '')
            if header.startswith('Bearer '):
                Token.revoke_token(header[7:].strip())
        return success_response(message=_("Signed out."))

    @http.route('/api/v1/auth/me', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    def me(self, **kw):
        device = current_device()
        payload = _user_payload(current_user())
        payload['device'] = {
            'id': _i(device.id),
            'device_uuid': _s(device.device_uuid),
            'device_number': _s(device.device_number),
            'active': _b(device.active),
            'last_sync_at': _s(device.last_sync_at),
        } if device else None
        return success_response(data=payload)

    @http.route('/api/v1/auth/change-password', type='http', auth='public',
                methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    def change_password(self, **kw):
        body = get_json_body()
        current = body.get('current_password') or ''
        new_password = body.get('new_password') or ''
        if len(new_password) < 8:
            return error_response(
                _("The new password must be at least 8 characters."),
                status=400, code=ErrCode.VALIDATION)
        user = current_user()
        try:
            user._check_credentials(
                {'login': user.login, 'password': current, 'type': 'password'},
                {'interactive': False})
        except AccessDenied:
            return error_response(
                _("The current password is not correct."),
                status=401, code=ErrCode.UNAUTHORIZED)
        user.sudo().write({'password': new_password})
        # Every other token was issued against the old password.
        request.env['van.sales.api.token'].sudo().revoke_all_for_user(user.id)
        return success_response(
            message=_("Password changed. Sign in again on every device."))
