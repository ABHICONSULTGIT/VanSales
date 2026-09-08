# Part of the Van Sales project.

import json
import logging
import threading

from odoo import api, models

_logger = logging.getLogger(__name__)

# Optional dependency. Deliberately not declared in the manifest's
# external_dependencies: Odoo refuses to load a module whose external
# dependency is missing, and the API must not be blocked by an optional push
# library. Install with `pip install firebase-admin` to enable notifications.
try:
    import firebase_admin
    from firebase_admin import credentials, messaging
except ImportError:                                      # pragma: no cover
    firebase_admin = None
    credentials = messaging = None

PARAM_SERVICE_ACCOUNT = 'van_sales.fcm_service_account_json'
PARAM_ANDROID_CHANNEL = 'van_sales.fcm_android_channel_id'
FIREBASE_APP_NAME = 'van_sales'

_init_lock = threading.Lock()


class VanSalesFcmService(models.AbstractModel):
    """Firebase sender.

    An AbstractModel so it is reachable as ``self.env['van.sales.fcm.service']``
    from controllers and crons alike. The Firebase handle is cached on the
    Python class for the worker's lifetime and initialised once under a lock.

    The service account JSON lives in a system parameter, not a file on disk,
    and the parameter is van-sales specific - so this can point at its own
    Firebase project or share another one, as a configuration choice.
    """

    _name = 'van.sales.fcm.service'
    _description = "Van Sales Firebase Sender"

    _firebase_app = None

    @api.model
    def _service_account_json(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            PARAM_SERVICE_ACCOUNT)

    @api.model
    def is_configured(self):
        return bool(firebase_admin) and bool(self._service_account_json())

    @api.model
    def _get_app(self):
        if firebase_admin is None:
            _logger.info(
                "Van Sales: firebase_admin is not installed; push disabled.")
            return None
        if VanSalesFcmService._firebase_app is not None:
            return VanSalesFcmService._firebase_app
        with _init_lock:
            if VanSalesFcmService._firebase_app is None:
                raw = self._service_account_json()
                if not raw:
                    _logger.info(
                        "Van Sales: FCM service account not configured "
                        "(system parameter '%s'); push disabled.",
                        PARAM_SERVICE_ACCOUNT)
                    return None
                try:
                    cred = credentials.Certificate(json.loads(raw))
                except (ValueError, json.JSONDecodeError) as err:
                    _logger.error(
                        "Van Sales: invalid FCM service account JSON: %s", err)
                    return None
                try:
                    VanSalesFcmService._firebase_app = firebase_admin.get_app(
                        FIREBASE_APP_NAME)
                except ValueError:
                    VanSalesFcmService._firebase_app = firebase_admin.initialize_app(
                        cred, name=FIREBASE_APP_NAME)
        return VanSalesFcmService._firebase_app

    @api.model
    def send_to_user(self, user_id, title, body, data=None, dry_run=False):
        """Push to every active device of a user. Returns how many landed."""
        if not self._get_app():
            return 0
        devices = self.env['van.sales.device'].sudo().search([
            ('user_id', '=', user_id),
            ('active', '=', True),
            ('fcm_token', '!=', False),
        ])
        tokens = [d.fcm_token for d in devices if d.fcm_token]
        if not tokens:
            return 0
        return self._send_to_tokens(tokens, title, body, data, dry_run=dry_run)

    @api.model
    def _send_to_tokens(self, tokens, title, body, data=None, dry_run=False):
        app = self._get_app()
        if not app or not tokens:
            return 0
        channel = self.env['ir.config_parameter'].sudo().get_param(
            PARAM_ANDROID_CHANNEL) or None
        payload = {str(k): str(v) for k, v in (data or {}).items()}
        message = messaging.MulticastMessage(
            tokens=list(tokens),
            notification=messaging.Notification(title=title, body=body or ''),
            data=payload,
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(channel_id=channel)
                if channel else None),
        )
        try:
            response = messaging.send_each_for_multicast(
                message, dry_run=dry_run, app=app)
        except Exception:                                # noqa: BLE001
            _logger.exception("Van Sales: FCM send failed")
            raise
        self._deactivate_dead_tokens(tokens, response)
        return response.success_count

    @api.model
    def _deactivate_dead_tokens(self, tokens, response):
        """Clear tokens Firebase reports as unregistered.

        A stale token otherwise keeps failing on every notification forever.
        """
        dead = []
        for token, result in zip(tokens, getattr(response, 'responses', [])):
            if result.success:
                continue
            error = getattr(result, 'exception', None)
            if error is not None and 'not registered' in str(error).lower():
                dead.append(token)
        if dead:
            self.env['van.sales.device'].sudo().search([
                ('fcm_token', 'in', dead),
            ]).write({'fcm_token': False})
            _logger.info("Van Sales: cleared %s dead FCM token(s).", len(dead))
