"""Shared plumbing for every Van Sales API endpoint.

Follows the Red Ladder mobile API architecture: one JSON envelope, hashed
bearer tokens validated by a decorator rather than by Odoo's own auth, a full
request/response log written on its own cursor, and null normalisation so the
Flutter client never receives Odoo's ``False``.
"""

import functools
import json
import logging
import time
import traceback as tb

from odoo import SUPERUSER_ID, api
from odoo.exceptions import AccessDenied
from odoo.http import request
from odoo.orm.registry import Registry

_logger = logging.getLogger(__name__)

API_PREFIX = '/api/v1/'
MAX_LOG_BODY = 50000          # 50 KB per logged body
PARAM_LOG_ENABLED = 'van_sales.api_log_enabled'

CORS_HEADERS = [
    ('Access-Control-Allow-Origin', '*'),
    ('Access-Control-Allow-Headers',
     'Content-Type, Authorization, X-Device-ID, X-App-Version'),
    ('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, PATCH, OPTIONS'),
]


# =============================================================================
# REQUEST TIMING
# =============================================================================

def _start_timer():
    """Stamp the start time on the request itself.

    Deliberately not a module-level dict keyed by ``id(request)``: any request
    that returns without passing through the envelope would leave an entry
    behind, and the dict grows for the life of the worker.
    """
    try:
        request._van_sales_started = time.time()
    except Exception:                                    # noqa: BLE001
        pass


def _elapsed_ms():
    started = getattr(request, '_van_sales_started', None)
    return round((time.time() - started) * 1000, 2) if started else 0.0


# =============================================================================
# REQUEST / RESPONSE LOG
# =============================================================================

def _log_api(response_data, status=200, error_info=None):
    """Record the call in van.sales.api.log. Never raises."""
    try:
        req = request.httprequest
        path = req.path or ''
        if not path.startswith(API_PREFIX):
            return
        try:
            enabled = request.env['ir.config_parameter'].sudo().get_param(
                PARAM_LOG_ENABLED, 'True')
            if str(enabled).strip().lower() in ('false', '0', ''):
                return
        except Exception:                                # noqa: BLE001
            pass

        headers = dict(req.headers)
        for key in list(headers):
            if key.lower() == 'authorization':
                headers[key] = 'Bearer ***'

        def _clip(text):
            text = text or ''
            return (text[:MAX_LOG_BODY] + '\n... [TRUNCATED]'
                    if len(text) > MAX_LOG_BODY else text)

        try:
            body = _clip(req.get_data(as_text=True))
        except Exception:                                # noqa: BLE001
            body = ''
        try:
            response_body = _clip(json.dumps(
                response_data, ensure_ascii=False, default=str))
        except Exception:                                # noqa: BLE001
            response_body = _clip(str(response_data))

        user_id = None
        try:
            if request.env and request.env.uid and request.env.uid != SUPERUSER_ID:
                user_id = request.env.uid
        except Exception:                                # noqa: BLE001
            pass

        values = {
            'name': path,
            'method': req.method,
            'full_url': req.url,
            'query_params': json.dumps(dict(req.args)) if req.args else '{}',
            'request_headers': json.dumps(headers, indent=2, ensure_ascii=False),
            'request_body': body,
            'response_body': response_body,
            'http_status': status,
            'is_success': status < 400,
            'is_error': status >= 400,
            'duration_ms': _elapsed_ms(),
            'user_id': user_id,
            'device_uuid': req.headers.get('X-Device-ID', ''),
            'app_version': req.headers.get('X-App-Version', ''),
            'ip_address': req.remote_addr or '',
        }
        if error_info:
            values.update({
                'error_type': error_info.get('type', ''),
                'error_message': error_info.get('message', ''),
                'traceback': _clip(error_info.get('traceback', '')),
            })

        # A brand-new cursor with its own commit: the log has to survive the
        # request's own transaction rolling back, which is exactly the case
        # worth debugging.
        db_name = request.db or (request.env.cr.dbname if request.env else None)
        if db_name:
            with Registry(db_name).cursor() as cr:
                api.Environment(cr, SUPERUSER_ID, {})['van.sales.api.log'].create(values)
                cr.commit()
    except Exception:                                    # noqa: BLE001
        _logger.exception("Van Sales API: logging failed")


# =============================================================================
# RESPONSE ENVELOPE
# =============================================================================

def _json_response(success=True, message=None, data=None, error=None,
                   status=200, pagination=None, extra=None):
    body = {
        # 'ok' mirrors 'success'. Purely additive: it lets the mobile client
        # use one success check across both this envelope and the
        # {ok, data, error} envelope the /api/v1/app/ endpoints answer with.
        # Nothing that reads 'success' is affected.
        'ok': success,
        'success': success,
        'message': message,
        'data': data,
        'error': error,
    }
    if pagination:
        body['pagination'] = pagination
    if extra:
        body.update(extra)

    _log_api(
        body, status=status,
        error_info={'type': 'HTTP %s' % status, 'message': message}
        if status >= 400 else None)

    return request.make_response(
        json.dumps(body, default=str, ensure_ascii=False),
        headers=[('Content-Type', 'application/json; charset=utf-8')] + CORS_HEADERS,
        status=status,
    )


def success_response(data=None, message=None, pagination=None, status=200,
                     extra=None):
    return _json_response(success=True, message=message, data=data,
                          pagination=pagination, status=status, extra=extra)


def error_response(message=None, error=None, status=400, code=None, data=None):
    """Error envelope.

    ``code`` carries a stable machine-readable identifier - the requirement
    document asks for errors that "map cleanly to user-facing app messages"
    (§6.2), which a translated sentence cannot do.
    """
    return _json_response(
        success=False, message=message, error=error or message,
        data=data, status=status,
        extra={'code': code} if code else None)


def handle_options():
    return request.make_response(
        '', headers=CORS_HEADERS + [('Access-Control-Max-Age', '86400')],
        status=200)


# =============================================================================
# ERROR CODES  (§6.2 - "map cleanly to user-facing app messages")
# =============================================================================

class ErrCode:
    UNAUTHORIZED = 'UNAUTHORIZED'
    TOKEN_EXPIRED = 'TOKEN_EXPIRED'
    DEVICE_UNKNOWN = 'DEVICE_UNKNOWN'
    DEVICE_INACTIVE = 'DEVICE_INACTIVE'
    DEVICE_NOT_BOUND = 'DEVICE_NOT_BOUND'
    VALIDATION = 'VALIDATION_ERROR'
    NOT_FOUND = 'NOT_FOUND'
    RATE_LIMITED = 'RATE_LIMITED'
    STOCK_INSUFFICIENT = 'STOCK_INSUFFICIENT'
    CREDIT_LIMIT_EXCEEDED = 'CREDIT_LIMIT_EXCEEDED'
    INVOICE_ALREADY_PAID = 'INVOICE_ALREADY_PAID'
    ALREADY_PROCESSED = 'ALREADY_PROCESSED'
    STALE_PAYLOAD = 'STALE_PAYLOAD'
    UNSUPPORTED_MODEL = 'UNSUPPORTED_MODEL'
    SERVER_ERROR = 'SERVER_ERROR'


# =============================================================================
# NULL NORMALISATION - the client never sees Odoo's False
# =============================================================================

def _s(value):
    return '' if value is False or value is None else str(value)


def _i(value):
    if value is False or value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _f(value):
    if value is False or value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _b(value):
    return bool(value)


def _l(value):
    if value is False or value is None:
        return []
    return value if isinstance(value, list) else list(value)


def _dt(value):
    """Datetime/date as an ISO-8601 string, or '' when unset."""
    if not value:
        return ''
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


def _m2o(record):
    """A many2one as {'id': int, 'name': str} - never a bare False."""
    if not record:
        return {'id': 0, 'name': ''}
    return {'id': _i(record.id), 'name': _s(record.display_name)}


# =============================================================================
# AUTHENTICATION
# =============================================================================

def _bearer_token():
    header = request.httprequest.headers.get('Authorization', '') or ''
    if not header.startswith('Bearer '):
        return None
    return header[7:].strip() or None


def _resolve_device(user):
    """The device this call claims to come from, if any.

    Unlike Red Ladder - where ``X-Device-ID`` is an optional hint used to merge
    a guest cart - the device is a first-class record here: it carries the
    offline numbering sequence and the sync watermark. Endpoints that need it
    use @device_required.
    """
    uuid = request.httprequest.headers.get('X-Device-ID', '') or ''
    if not uuid:
        return request.env['van.sales.device']
    return request.env['van.sales.device'].sudo().search([
        ('device_uuid', '=', uuid),
    ], limit=1)


def token_required(func):
    """Reject anything without a valid bearer token; switch to that user."""
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        _start_timer()
        if request.httprequest.method == 'OPTIONS':
            return handle_options()
        raw_token = _bearer_token()
        if not raw_token:
            return error_response(
                'Missing or invalid Authorization header.',
                status=401, code=ErrCode.UNAUTHORIZED)
        try:
            user = request.env['van.sales.api.token'].sudo().validate_token(raw_token)
        except AccessDenied:
            return error_response(
                'Invalid or expired token.',
                status=401, code=ErrCode.TOKEN_EXPIRED)
        except Exception:                                # noqa: BLE001
            _logger.exception("Van Sales API: token validation failed")
            return error_response(
                'Authentication error.', status=401, code=ErrCode.UNAUTHORIZED)

        request.update_env(user=user.id)
        request._van_sales_device = _resolve_device(user)
        try:
            return func(self, *args, **kwargs)
        except Exception as exc:                         # noqa: BLE001
            _logger.exception("Van Sales API: %s failed", request.httprequest.path)
            _log_api({'success': False, 'error': str(exc)}, status=500,
                     error_info={'type': type(exc).__name__,
                                 'message': str(exc),
                                 'traceback': tb.format_exc()})
            return error_response(
                'An unexpected error occurred.',
                status=500, code=ErrCode.SERVER_ERROR)
    return wrapper


def device_required(func):
    """Also require the call to name a registered, active, bound device.

    Applied on top of @token_required. Sync cannot work without knowing which
    device is asking: the watermark and the offline numbering both live on it.
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        device = getattr(request, '_van_sales_device', None)
        if not device:
            return error_response(
                'Unknown device. Register it before syncing.',
                status=403, code=ErrCode.DEVICE_UNKNOWN)
        if not device.active:
            return error_response(
                'This device has been deactivated. Contact the office.',
                status=403, code=ErrCode.DEVICE_INACTIVE)
        if device.user_id != request.env.user:
            return error_response(
                'This device is registered to another user.',
                status=403, code=ErrCode.DEVICE_UNKNOWN)
        if not device.van_id:
            return error_response(
                'This device is not bound to a van yet. Contact the office.',
                status=403, code=ErrCode.DEVICE_NOT_BOUND)
        return func(self, *args, **kwargs)
    return wrapper


def public_endpoint(func):
    """No auth, logging only - login, and CORS preflight."""
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        _start_timer()
        if request.httprequest.method == 'OPTIONS':
            return handle_options()
        try:
            return func(self, *args, **kwargs)
        except Exception as exc:                         # noqa: BLE001
            _logger.exception("Van Sales API: %s failed", request.httprequest.path)
            _log_api({'success': False, 'error': str(exc)}, status=500,
                     error_info={'type': type(exc).__name__,
                                 'message': str(exc),
                                 'traceback': tb.format_exc()})
            return error_response(
                'An unexpected error occurred.',
                status=500, code=ErrCode.SERVER_ERROR)
    return wrapper


# =============================================================================
# CURRENT CONTEXT HELPERS
# =============================================================================

def current_user():
    return request.env.user


def current_device():
    return getattr(request, '_van_sales_device', request.env['van.sales.device'])


def current_van():
    return current_device().van_id


# =============================================================================
# REQUEST BODY / QUERY
# =============================================================================

def get_json_body():
    try:
        raw = request.httprequest.get_data()
        if not raw:
            return {}
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def get_query_str(name, default=None):
    return request.httprequest.args.get(name, default)


def get_query_int(name, default=None):
    raw = request.httprequest.args.get(name)
    if raw in (None, ''):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def get_query_bool(name, default=False):
    raw = request.httprequest.args.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ('1', 'true', 'yes')


# =============================================================================
# PAGINATION
# =============================================================================

MAX_PAGE_SIZE = 200


def paginate(model_name, domain, page=1, limit=50, order=None, env=None):
    env = env or request.env
    Model = env[model_name].sudo()
    page = max(int(page or 1), 1)
    limit = min(max(int(limit or 50), 1), MAX_PAGE_SIZE)
    total = Model.search_count(domain)
    records = Model.search(domain, offset=(page - 1) * limit,
                           limit=limit, order=order)
    return records, {
        'page': page,
        'limit': limit,
        'total': total,
        'total_pages': max((total + limit - 1) // limit, 1),
        'has_next': page * limit < total,
        'has_prev': page > 1,
    }


# =============================================================================
# MISC
# =============================================================================

def get_base_url():
    return request.env['ir.config_parameter'].sudo().get_param(
        'web.base.url', '').rstrip('/')


def image_url(model, record_id, field='image_128'):
    if not record_id:
        return ''
    return '%s/web/image/%s/%s/%s' % (get_base_url(), model, record_id, field)
