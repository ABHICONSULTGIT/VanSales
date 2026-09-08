# Part of the Van Sales project.

from odoo import api, fields, models

PARAM_RETENTION_DAYS = 'van_sales.api_log_retention_days'
DEFAULT_RETENTION_DAYS = 30


class VanSalesApiLog(models.Model):
    """Every /api/v1/ request and its response.

    Written on a fresh cursor by the controller, so an entry survives the
    request's own transaction rolling back - which is precisely the case worth
    debugging.
    """

    _name = 'van.sales.api.log'
    _description = "Van Sales API Request Log"
    _order = 'request_time desc, id desc'
    _log_access = False

    name = fields.Char(string="Endpoint", index=True, readonly=True)
    method = fields.Selection(
        selection=[('GET', 'GET'), ('POST', 'POST'), ('PUT', 'PUT'),
                   ('PATCH', 'PATCH'), ('DELETE', 'DELETE'),
                   ('OPTIONS', 'OPTIONS')],
        string="Method", index=True, readonly=True)
    full_url = fields.Char(readonly=True)
    query_params = fields.Text(readonly=True)
    request_headers = fields.Text(readonly=True)
    request_body = fields.Text(readonly=True)
    response_body = fields.Text(readonly=True)
    http_status = fields.Integer(index=True, readonly=True)
    is_success = fields.Boolean(index=True, readonly=True)
    is_error = fields.Boolean(index=True, readonly=True)
    user_id = fields.Many2one('res.users', index=True, readonly=True)
    device_uuid = fields.Char(string="Device", index=True, readonly=True)
    app_version = fields.Char(readonly=True)
    ip_address = fields.Char(readonly=True)
    request_time = fields.Datetime(
        index=True, readonly=True, default=fields.Datetime.now)
    duration_ms = fields.Float(readonly=True)
    error_type = fields.Char(readonly=True)
    error_message = fields.Text(readonly=True)
    traceback = fields.Text(readonly=True)
    endpoint_group = fields.Selection(
        selection=[('auth', "Authentication"), ('device', "Device"),
                   ('sync', "Sync"), ('lookup', "Lookup"),
                   ('notification', "Notifications"), ('other', "Other")],
        string="Group", index=True, readonly=True,
        compute='_compute_endpoint_group', store=True)

    @api.depends('name')
    def _compute_endpoint_group(self):
        for record in self:
            path = record.name or ''
            if '/auth/' in path:
                record.endpoint_group = 'auth'
            elif '/device' in path:
                record.endpoint_group = 'device'
            elif '/sync/' in path:
                record.endpoint_group = 'sync'
            elif '/notifications' in path:
                record.endpoint_group = 'notification'
            elif '/lookup/' in path:
                record.endpoint_group = 'lookup'
            else:
                record.endpoint_group = 'other'

    @api.model
    def _cron_cleanup_old(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(
            PARAM_RETENTION_DAYS, DEFAULT_RETENTION_DAYS)
        try:
            days = max(int(raw), 1)
        except (TypeError, ValueError):
            days = DEFAULT_RETENTION_DAYS
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        self.sudo().search([('request_time', '<', cutoff)]).unlink()
        return True
