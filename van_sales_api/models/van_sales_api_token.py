# Part of the Van Sales project.

import hashlib
import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied

PARAM_EXPIRY_DAYS = 'van_sales.api_token_expiry_days'
DEFAULT_EXPIRY_DAYS = 30


class VanSalesApiToken(models.Model):
    """Bearer token for the mobile app.

    Only the SHA-256 hash is stored. The raw token exists exactly once, in the
    login response - so a leaked database gives an attacker nothing usable.
    """

    _name = 'van.sales.api.token'
    _description = "Van Sales API Token"
    _order = 'create_date desc'

    name = fields.Char(
        string="Token Hash", required=True, index=True, copy=False, readonly=True)
    user_id = fields.Many2one(
        'res.users', string="User", required=True, ondelete='cascade', index=True)
    device_uuid = fields.Char(string="Device", index=True)
    expires_at = fields.Datetime(string="Expires At", required=True, index=True)
    active = fields.Boolean(default=True)
    ip_address = fields.Char(string="Issued To IP")
    app_version = fields.Char(string="App Version")
    last_used = fields.Datetime(string="Last Used")

    # models.Constraint, not _sql_constraints: Odoo 19 silently ignores the
    # old form, which would leave this uniqueness unenforced in the database.
    _token_unique = models.Constraint(
        'UNIQUE(name)', "This API token already exists.")

    @api.model
    def _expiry_days(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(
            PARAM_EXPIRY_DAYS, DEFAULT_EXPIRY_DAYS)
        try:
            return max(int(raw), 1)
        except (TypeError, ValueError):
            return DEFAULT_EXPIRY_DAYS

    @api.model
    def generate_token(self, user_id, device_uuid=None, ip_address=None,
                       app_version=None):
        raw_token = secrets.token_urlsafe(64)
        self.sudo().create({
            'name': hashlib.sha256(raw_token.encode()).hexdigest(),
            'user_id': user_id,
            'device_uuid': device_uuid or '',
            'ip_address': ip_address or '',
            'app_version': app_version or '',
            'expires_at': fields.Datetime.now() + timedelta(days=self._expiry_days()),
        })
        return raw_token

    @api.model
    def validate_token(self, raw_token):
        token = self.sudo().search([
            ('name', '=', hashlib.sha256(raw_token.encode()).hexdigest()),
            ('active', '=', True),
            ('expires_at', '>', fields.Datetime.now()),
        ], limit=1)
        if not token:
            raise AccessDenied(_("Invalid or expired token."))
        if not token.user_id.active:
            raise AccessDenied(_("This user account is no longer active."))
        token.write({'last_used': fields.Datetime.now()})
        return token.user_id

    @api.model
    def revoke_token(self, raw_token):
        token = self.sudo().search([
            ('name', '=', hashlib.sha256(raw_token.encode()).hexdigest()),
        ], limit=1)
        if token:
            token.active = False
        return True

    @api.model
    def revoke_all_for_user(self, user_id):
        self.sudo().search([
            ('user_id', '=', user_id), ('active', '=', True),
        ]).write({'active': False})
        return True

    @api.model
    def _cron_cleanup_expired(self):
        """Delete tokens that expired more than a week ago."""
        cutoff = fields.Datetime.now() - timedelta(days=7)
        self.sudo().search([('expires_at', '<', cutoff)]).unlink()
        return True
