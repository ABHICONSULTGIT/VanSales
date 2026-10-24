# Part of the Van Sales project.

import hashlib
import secrets
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessDenied

DEFAULT_TOKEN_DAYS = 30


class VanSalesApiToken(models.Model):
    """A mobile app login. Only the SHA-256 of the token is stored."""

    _name = 'van.sales.api.token'
    _description = "Van Sales Mobile API Token"
    _order = 'create_date desc'

    name = fields.Char(string="Token Hash", required=True, index=True, copy=False)
    user_id = fields.Many2one(
        comodel_name='res.users', string="User", required=True,
        ondelete='cascade', index=True)
    expires_at = fields.Datetime(string="Expires At", required=True)
    active = fields.Boolean(default=True)
    device_info = fields.Char(string="Device")
    ip_address = fields.Char(string="IP Address")
    last_used = fields.Datetime(string="Last Used")

    _token_uniq = models.Constraint('UNIQUE(name)', "Token must be unique.")

    @staticmethod
    def _hash(raw_token):
        return hashlib.sha256(raw_token.encode()).hexdigest()

    @api.model
    def _token_days(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'van_sales_mobile_api.token_days')
        try:
            return max(int(value), 1) if value else DEFAULT_TOKEN_DAYS
        except ValueError:
            return DEFAULT_TOKEN_DAYS

    @api.model
    def _issue(self, user, device_info=None, ip_address=None):
        """Create a token for ``user``. Returns ``(raw_token, record)``."""
        raw_token = secrets.token_urlsafe(48)
        record = self.sudo().create({
            'name': self._hash(raw_token),
            'user_id': user.id,
            'expires_at': fields.Datetime.now() + timedelta(days=self._token_days()),
            'device_info': (device_info or '')[:255],
            'ip_address': ip_address or '',
        })
        return raw_token, record

    @api.model
    def _validate(self, raw_token):
        """The token's record if it is active and not expired, else AccessDenied."""
        record = self.sudo().search([
            ('name', '=', self._hash(raw_token)),
            ('expires_at', '>', fields.Datetime.now()),
        ], limit=1)
        if not record or not record.user_id.active:
            raise AccessDenied()
        now = fields.Datetime.now()
        # Throttled: one write per token per minute is plenty for "last seen".
        if not record.last_used or (now - record.last_used).total_seconds() > 60:
            record.last_used = now
        return record

    @api.model
    def _revoke_user(self, user):
        self.sudo().search([('user_id', '=', user.id)]).active = False

    @api.model
    def _cron_cleanup_expired(self):
        cutoff = fields.Datetime.now() - timedelta(days=7)
        self.sudo().with_context(active_test=False).search([
            '|', ('expires_at', '<', cutoff), ('active', '=', False),
        ]).unlink()
