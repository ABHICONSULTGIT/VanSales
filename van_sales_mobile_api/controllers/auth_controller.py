# Part of the Van Sales project.

import logging

from odoo import http
from odoo.exceptions import AccessDenied
from odoo.http import request

from .base import (
    API_PREFIX, SALESMAN_GROUP, ApiError, body, fmt_datetime, me, my_van, ok,
    public, require, token_required, van_payload,
)

_logger = logging.getLogger(__name__)

FORGOT_REPLY = ("If this account exists, a password reset link has been sent "
                "to its email address.")


def session_payload(user, raw_token=None, token=None):
    company = user.company_id
    data = {
        'user': {
            'id': user.id,
            'name': user.name,
            'login': user.login,
            'email': user.email or None,
            'phone': user.partner_id.phone or None,
        },
        'company': {
            'id': company.id,
            'name': company.name,
            'currency': company.currency_id.name,
        },
        'van': van_payload(my_van(required=False)),
    }
    if raw_token:
        data = {'token': raw_token,
                'expires_at': fmt_datetime(token.expires_at), **data}
    return data


def issue_token(user, device_info=None):
    return request.env['van.sales.api.token'].sudo()._issue(
        user, device_info=device_info,
        ip_address=request.httprequest.remote_addr)


class VanSalesAuthController(http.Controller):

    @http.route(API_PREFIX + '/auth/login', type='http', auth='public',
                methods=['POST'], csrf=False, cors='*')
    @public
    def login(self, **kw):
        data = body()
        require(data, 'login', 'password')
        credential = {'type': 'password', 'login': str(data['login']).strip(),
                      'password': str(data['password'])}
        try:
            auth_info = request.env['res.users'].sudo().authenticate(
                credential, {'interactive': False})
        except AccessDenied:
            raise ApiError("Incorrect login or password.", 401)
        user = request.env['res.users'].sudo().browse(auth_info['uid'])
        if not user._is_internal() or not user.has_group(SALESMAN_GROUP):
            raise ApiError("This account is not set up for Van Sales.", 403)
        request.update_env(user=user.id)
        raw, token = issue_token(user, data.get('device_info'))
        return ok(session_payload(me(), raw, token), "Login successful.")

    @http.route(API_PREFIX + '/auth/logout', type='http', auth='public',
                methods=['POST'], csrf=False, cors='*')
    @token_required
    def logout(self, **kw):
        request.api_token.sudo().active = False
        return ok(None, "Logged out.")

    @http.route(API_PREFIX + '/auth/me', type='http', auth='public',
                methods=['GET'], csrf=False, cors='*')
    @token_required
    def whoami(self, **kw):
        return ok(session_payload(me()))

    @http.route(API_PREFIX + '/auth/refresh', type='http', auth='public',
                methods=['POST'], csrf=False, cors='*')
    @token_required
    def refresh(self, **kw):
        old = request.api_token.sudo()
        raw, token = issue_token(me(), old.device_info)
        old.active = False
        return ok({'token': raw, 'expires_at': fmt_datetime(token.expires_at)},
                  "Token refreshed.")

    @http.route(API_PREFIX + '/auth/change-password', type='http',
                auth='public', methods=['POST'], csrf=False, cors='*')
    @token_required
    def change_password(self, **kw):
        data = body()
        require(data, 'old_password', 'new_password')
        if data['old_password'] == data['new_password']:
            raise ApiError("The new password must be different.")
        try:
            # Odoo's own method: checks the old password as this user, applies
            # the password policy, and stores the new one.
            request.env['res.users'].change_password(
                data['old_password'], data['new_password'])
        except AccessDenied:
            raise ApiError("The current password is incorrect.")
        user = me()
        Token = request.env['van.sales.api.token'].sudo()
        Token._revoke_user(user)
        raw, token = issue_token(user, request.api_token.device_info)
        return ok({'token': raw, 'expires_at': fmt_datetime(token.expires_at)},
                  "Password changed. You are signed out on other devices.")

    @http.route(API_PREFIX + '/auth/forgot-password', type='http',
                auth='public', methods=['POST'], csrf=False, cors='*')
    @public
    def forgot_password(self, **kw):
        data = body()
        require(data, 'login')
        user = request.env['res.users'].sudo().search(
            [('login', '=', str(data['login']).strip())], limit=1)
        if user and user.has_group(SALESMAN_GROUP):
            try:
                with request.env.cr.savepoint():
                    user.action_reset_password()
            except Exception:
                # Same reply either way, so the app cannot be used to find out
                # which logins exist. The cause is in the server log.
                _logger.exception("Password reset email failed for user %s",
                                  user.id)
        return ok(None, FORGOT_REPLY)
