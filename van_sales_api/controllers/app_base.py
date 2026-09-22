# Part of the Van Sales project.
"""Shared plumbing for the Vantix mobile application contract.

The endpoints under ``/api/v1/app/`` answer the shape described in the mobile
team's *Vantix Van Sales - Complete API Specification v1.0* (2026-08-19): an
``{ok, data, error}`` envelope, ``camelCase`` field names and **string**
identifiers.

Why a separate namespace rather than reshaping ``/api/v1/``
-----------------------------------------------------------
1. The five ``/api/v1/auth/`` routes are already approved by the mobile team.
   Nothing here touches them.
2. Odoo builds one routing map from every controller. Registering a second
   route on an existing path (``/api/v1/notifications``, for instance) would
   silently shadow the first - a failure that shows up in production, not at
   install. A distinct prefix makes a collision impossible.

The mobile app sets its base URL to ``https://<host>/api/v1/app`` and then
every path in the specification resolves exactly as written. The one exception
is authentication, which stays at ``/api/v1/auth/`` with the existing envelope.

**Everything in this package is read-only.** Writes continue to go through
``POST /api/v1/sync/push``.
"""

import functools
import json
import logging

from odoo.exceptions import (AccessDenied, AccessError, UserError,
                             ValidationError)
from odoo.http import request

from .base import (CORS_HEADERS, ErrCode, _bearer_token, _log_api,
                   _resolve_device, _start_timer, handle_options)

_logger = logging.getLogger(__name__)


# =============================================================================
# ENVELOPE  -  {ok, data, error{code, message, field, retryable}}
# =============================================================================

PARAM_LOG_BODIES = 'van_sales.api_log_app_bodies'


def _loggable(body, status):
    """What goes into van.sales.api.log for this response.

    Read endpoints are called far more often than sync - a product list on
    every scroll - and van.sales.api.log stores the full response body, on its
    own cursor, with a 30-day retention. Logging a 50 KB catalogue page on
    every call would grow the table by gigabytes a month at fleet scale.

    So successful app-layer responses are logged as a **summary** by default;
    failures are always logged in full, because those are the ones worth
    reading. Set `van_sales.api_log_app_bodies` to True to capture everything
    while debugging.
    """
    if status >= 400:
        return body
    try:
        full = str(request.env['ir.config_parameter'].sudo().get_param(
            PARAM_LOG_BODIES, 'False')).strip().lower() in ('1', 'true', 'yes')
    except Exception:                                    # noqa: BLE001
        full = False
    if full:
        return body
    data = body.get('data')
    return {
        'ok': body.get('ok'),
        'rows': len(data) if isinstance(data, list) else (1 if data else 0),
        'pagination': body.get('pagination'),
        'note': 'body not logged - set %s to True to capture it' % PARAM_LOG_BODIES,
    }


def _envelope(body, status):
    _log_api(_loggable(body, status), status=status,
             error_info=({'type': 'HTTP %s' % status,
                          'message': (body.get('error') or {}).get('message', '')}
                         if status >= 400 else None))
    return request.make_response(
        json.dumps(body, default=str, ensure_ascii=False),
        headers=[('Content-Type', 'application/json; charset=utf-8')] + CORS_HEADERS,
        status=status)


#: base.paginate() answers in snake_case, which is right for the /api/v1/
#: endpoints and wrong here. Converted in one place rather than at every call
#: site, so a new endpoint cannot forget.
_PAGINATION_KEYS = {
    'total_pages': 'totalPages',
    'has_next': 'hasNext',
    'has_prev': 'hasPrev',
}


def app_pagination(pagination):
    if not pagination:
        return None
    return {_PAGINATION_KEYS.get(key, key): value
            for key, value in pagination.items()}


def app_response(data=None, pagination=None, status=200, extra=None):
    body = {'ok': True, 'data': data, 'error': None}
    if pagination:
        body['pagination'] = app_pagination(pagination)
    if extra:
        body.update(extra)
    return _envelope(body, status)


def app_error(message, code=ErrCode.VALIDATION, status=400, field=None,
              retryable=False):
    """Error envelope in the mobile contract's shape.

    ``retryable`` tells an offline client whether to re-queue the request. A
    server fault or a rate limit is worth retrying; a validation failure or a
    credit-limit rejection never is, and retrying it forever is how a device
    ends up with a stuck queue.
    """
    return _envelope({
        'ok': False,
        'data': None,
        'error': {
            'code': code,
            'message': message,
            'field': field,
            'retryable': bool(retryable),
        },
    }, status)


# Codes that are worth sending again unchanged.
RETRYABLE_CODES = (ErrCode.SERVER_ERROR, ErrCode.RATE_LIMITED)


# =============================================================================
# AUTHENTICATION
# =============================================================================

def app_token_required(func):
    """Bearer-token guard that fails in the *mobile contract's* error shape.

    Deliberately not reusing ``base.token_required``: that decorator emits the
    ``{success, message, data, error}`` envelope, so an expired token - the
    single most common error the app will meet - would come back in a shape
    the app cannot parse. The validation logic below is identical to it.
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        _start_timer()
        if request.httprequest.method == 'OPTIONS':
            return handle_options()

        raw_token = _bearer_token()
        if not raw_token:
            return app_error("Missing or invalid Authorization header.",
                             code=ErrCode.UNAUTHORIZED, status=401)
        try:
            user = request.env['van.sales.api.token'].sudo().validate_token(raw_token)
        except AccessDenied:
            return app_error("Invalid or expired token. Sign in again.",
                             code=ErrCode.TOKEN_EXPIRED, status=401)
        except Exception:                                    # noqa: BLE001
            _logger.exception("Van Sales app API: token validation failed")
            return app_error("Authentication error.",
                             code=ErrCode.UNAUTHORIZED, status=401)

        request.update_env(user=user.id)
        request._van_sales_device = _resolve_device(user)

        try:
            return func(self, *args, **kwargs)
        except AccessDenied:
            # Credentials went stale mid-request.
            return app_error("Invalid or expired token. Sign in again.",
                             code=ErrCode.TOKEN_EXPIRED, status=401)
        except AccessError as err:
            # AccessError subclasses UserError in Odoo, so it MUST be caught
            # first - otherwise a permission failure is reported to the app as
            # a 400 validation error and the salesman is told his data was
            # wrong when in fact he was not allowed to read it.
            return app_error(str(err), code=ErrCode.UNAUTHORIZED, status=403)
        except (UserError, ValidationError) as err:
            # A rule the business refused, not a fault: never retryable.
            return app_error(str(err), code=ErrCode.VALIDATION, status=400)
        except Exception as exc:                             # noqa: BLE001
            _logger.exception("Van Sales app API: %s failed",
                              request.httprequest.path)
            _log_api({'ok': False, 'error': str(exc)}, status=500,
                     error_info={'type': type(exc).__name__, 'message': str(exc)})
            return app_error("An unexpected error occurred.",
                             code=ErrCode.SERVER_ERROR, status=500, retryable=True)
    return wrapper


# =============================================================================
# SERIALISATION  -  string ids, camelCase, no Odoo False
# =============================================================================

def sid(value):
    """An identifier as an opaque **string**, '' when unset.

    The mobile contract types every id as a string. Odoo ids are integers, so
    they are stringified here and nowhere else. The app must treat the result
    as opaque: never parsed, sorted or used in arithmetic.
    """
    if not value:
        return ''
    if hasattr(value, 'id'):          # a recordset was passed by mistake
        value = value.id
    return str(value)


def opt(value):
    """``None`` when absent - for fields the contract types ``string?``.

    Used only where the specification's own examples show ``null``. Everywhere
    else an absent string is '' so the app never has to null-check.
    """
    if value is False or value is None or value == '':
        return None
    return str(value)


def s(value):
    return '' if value is False or value is None else str(value)


def f(value):
    if value is False or value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def i(value):
    if value is False or value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def b(value):
    return bool(value)


def dt(value):
    """ISO-8601, or '' when unset. The contract's dates are ISO strings."""
    if not value:
        return ''
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


# =============================================================================
# SCOPING  -  which van is asking, and what it may see
# =============================================================================

def app_van():
    """The van this request belongs to.

    Prefers the registered device (the authoritative binding). Falls back to
    the vehicle assigned to the signed-in salesman, mirroring exactly what
    ``auth_controller._user_payload`` already does, so a handset that has not
    called ``/device/register`` yet can still read.
    """
    device = getattr(request, '_van_sales_device', None)
    if device and device.van_id:
        return device.van_id
    # order='id' is deliberate: without it the pick is whatever Fleet's
    # default order happens to be, so a salesman assigned two vans could be
    # shown a different one from one request to the next.
    return request.env['fleet.vehicle'].sudo().search([
        ('is_sales_van', '=', True),
        ('salesman_user_id', '=', request.env.user.id),
    ], limit=1, order='id')


def app_partner_ids(van):
    """Customers this van deals with - everyone on its routes.

    The same rule as ``load_masters.ResPartner._van_partner_ids``, restated
    here because the sync loaders are chained (each receives the data selected
    before it) and cannot be called standalone. Keeping the rule identical is
    what stops a REST wrapper from returning a customer the sync layer would
    have withheld.
    """
    env = request.env
    partner_ids = set()
    if van:
        lines = env['van.sales.route.line'].sudo().search([
            ('route_id.van_id', '=', van.id),
            ('partner_id', '!=', False),
        ])
        partner_ids = set(lines.mapped('partner_id').ids)
    if env.user.partner_id:
        partner_ids.add(env.user.partner_id.id)
    return partner_ids


def app_partner_domain(van):
    """Domain restricting ``res.partner`` to this van's customers."""
    partner_ids = app_partner_ids(van)
    if not partner_ids:
        return [('id', '=', 0)]        # match nothing, rather than everything
    return [('id', 'in', list(partner_ids))]


def no_van_error():
    """The response for an endpoint that is meaningless without a van.

    Returned instead of an empty list, deliberately: "no van is assigned to
    you" and "you have no orders today" are different problems and need
    different screens. An empty list would send the salesman looking for
    orders that were never going to be there.
    """
    return app_error(
        "No van is assigned to this account. Contact the office.",
        code=ErrCode.DEVICE_NOT_BOUND, status=403)
