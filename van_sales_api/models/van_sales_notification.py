# Part of the Van Sales project.

import json
import logging

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.orm.registry import Registry

_logger = logging.getLogger(__name__)


class VanSalesNotification(models.Model):
    """A message for a salesman: stored first, pushed second.

    The record is written before any push is attempted, and the push runs
    **after commit** on its own cursor. So a Firebase outage can never roll
    back the business transaction that raised the notification, and the app
    can still read its history from /notifications even when no push landed.
    A cron sweeps anything still unsent.
    """

    _name = 'van.sales.notification'
    _description = "Van Sales Notification"
    _order = 'create_date desc, id desc'

    user_id = fields.Many2one(
        'res.users', string="Recipient", required=True, ondelete='cascade',
        index=True)
    title = fields.Char(required=True)
    body = fields.Text()
    notification_type = fields.Selection(
        selection=[
            ('plan', "Route or plan change"),
            ('load', "Van load ready"),
            ('approval', "Approval result"),
            ('stock', "Low van stock"),
            ('announcement', "Announcement"),
            ('system', "System"),
        ],
        string="Type", default='system', index=True)
    data = fields.Text(
        string="Payload", help="JSON delivered alongside the push, so the app "
                               "can deep-link to the right screen.")
    res_model = fields.Char(string="Related Model")
    res_id = fields.Integer(string="Related Record")
    is_read = fields.Boolean(default=False, index=True)
    is_sent = fields.Boolean(default=False, index=True, readonly=True)
    sent_at = fields.Datetime(readonly=True)
    send_error = fields.Char(readonly=True)

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._schedule_push()
        return records

    def _schedule_push(self):
        """Deliver after the current transaction commits, never inside it."""
        ids = self.ids
        dbname = self.env.cr.dbname
        if not ids:
            return

        def _deliver():
            try:
                with Registry(dbname).cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    env['van.sales.notification'].browse(ids)._deliver()
                    cr.commit()
            except Exception:                            # noqa: BLE001
                _logger.exception("Van Sales: push delivery failed")

        self.env.cr.postcommit.add(_deliver)

    def _deliver(self):
        service = self.env['van.sales.fcm.service']
        for record in self.exists().filtered(lambda n: not n.is_sent):
            try:
                sent = service.send_to_user(
                    record.user_id.id, record.title, record.body or '',
                    record._payload())
                record.write({
                    'is_sent': bool(sent),
                    'sent_at': fields.Datetime.now() if sent else False,
                    'send_error': '' if sent else 'No active device or FCM not configured',
                })
            except Exception as exc:                     # noqa: BLE001
                _logger.warning("Van Sales: push failed for %s: %s", record.id, exc)
                record.write({'send_error': str(exc)[:255]})

    def _payload(self):
        self.ensure_one()
        payload = {
            'notification_id': str(self.id),
            'type': self.notification_type or 'system',
        }
        if self.res_model:
            payload['res_model'] = self.res_model
            payload['res_id'] = str(self.res_id or 0)
        if self.data:
            try:
                extra = json.loads(self.data)
                if isinstance(extra, dict):
                    payload.update({k: str(v) for k, v in extra.items()})
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        return payload

    @api.model
    def _cron_send_pending(self):
        """Retry anything the after-commit delivery could not send."""
        pending = self.sudo().search([('is_sent', '=', False)], limit=200)
        pending._deliver()
        return True

    # ------------------------------------------------------------------
    # Admin actions
    # ------------------------------------------------------------------
    def action_send_now(self):
        self._deliver()
        return True

    def action_mark_read(self):
        self.write({'is_read': True})
        return True

    def action_open_related(self):
        self.ensure_one()
        if not (self.res_model and self.res_id):
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _("Related Record"),
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
        }
