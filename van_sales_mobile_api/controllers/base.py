# Part of the Van Sales project.
"""Shared plumbing for every mobile endpoint.

Kept deliberately small, in the Red Ladder style: one envelope, one
authentication decorator, a handful of helpers. Each controller reads like a
list of plain functions.

Envelope::

    {"success": bool, "message": str, "data": ..., "error": str|null,
     "pagination": {...}}            # lists only

Errors::

    400 bad input or a business rule (UserError / ValidationError)
    401 missing, invalid or expired token
    403 not allowed (AccessError, not a van salesman)
    404 not found (or not his)
    409 wrong state / no van assigned / duplicate
    500 anything unexpected (logged with traceback)

On any error the transaction is rolled back before the response is built,
so a request either does everything it says or nothing at all.
"""

import functools
import json
import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import fields
from odoo.exceptions import (
    AccessDenied, AccessError, MissingError, UserError, ValidationError,
)
from odoo.http import request

_logger = logging.getLogger(__name__)

API_PREFIX = '/api/v1'
SALESMAN_GROUP = 'van_sales_base.group_van_sales_user'
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class ApiError(Exception):
    """An expected failure with its HTTP status and a message for the app."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------
def _envelope(success, message='', data=None, error=None, pagination=None):
    body = {'success': success, 'message': message or '', 'data': data,
            'error': error}
    if pagination is not None:
        body['pagination'] = pagination
    return body


def ok(data=None, message='', pagination=None, status=200):
    return request.make_json_response(
        _envelope(True, message, data, None, pagination), status=status)


def fail(message, status=400):
    return request.make_json_response(
        _envelope(False, message, None, message), status=status)


def _run(func, self, args, kwargs):
    """Call the endpoint; turn every failure into an error response."""
    try:
        return func(self, *args, **kwargs)
    except ApiError as e:
        request.env.cr.rollback()
        return fail(e.message, e.status)
    except AccessError as e:
        request.env.cr.rollback()
        return fail(_first_line(e) or "You are not allowed to do this.", 403)
    except MissingError:
        request.env.cr.rollback()
        return fail("Record not found.", 404)
    except (UserError, ValidationError) as e:
        request.env.cr.rollback()
        return fail(_first_line(e), 400)
    except Exception:
        request.env.cr.rollback()
        _logger.exception("Mobile API error on %s", request.httprequest.path)
        return fail("Something went wrong on the server. Please try again.", 500)


def _first_line(exc):
    text = str(exc.args[0]) if exc.args else str(exc)
    return text.strip()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def _bearer():
    header = request.httprequest.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        return ''
    return header[7:].strip()


def token_required(func):
    """Validate the Bearer token and run the endpoint as its salesman."""
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        raw = _bearer()
        if not raw:
            return fail("Missing or invalid Authorization header.", 401)
        try:
            token = request.env['van.sales.api.token'].sudo()._validate(raw)
        except AccessDenied:
            return fail("Your session has expired. Please log in again.", 401)
        user = token.user_id
        if not user.has_group(SALESMAN_GROUP):
            return fail("This account is not set up for Van Sales.", 403)
        request.update_env(user=user.id)
        request.api_token = token
        return _run(func, self, args, kwargs)
    return wrapper


def public(func):
    """Endpoint without a token (login, forgot password)."""
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        return _run(func, self, args, kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------
def body():
    """The JSON request body as a dict (400 if it is not valid JSON)."""
    raw = request.httprequest.get_data(as_text=True)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        raise ApiError("The request body is not valid JSON.")
    if not isinstance(data, dict):
        raise ApiError("The request body must be a JSON object.")
    return data


def param(name, default=None):
    return request.httprequest.args.get(name, default)


def int_param(name, default=None):
    value = param(name)
    if value in (None, ''):
        return default
    try:
        return int(value)
    except ValueError:
        raise ApiError("'%s' must be a whole number." % name)


def bool_param(name, default=False):
    value = param(name)
    if value in (None, ''):
        return default
    return str(value).lower() in ('1', 'true', 'yes')


def date_param(name):
    value = param(name)
    if not value:
        return None
    try:
        return fields.Date.to_date(value)
    except ValueError:
        raise ApiError("'%s' must be a date as YYYY-MM-DD." % name)


def require(data, *names):
    missing = [n for n in names if data.get(n) in (None, '', [])]
    if missing:
        raise ApiError("Missing required field(s): %s." % ", ".join(missing))


def as_int(value, name):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError("'%s' must be a whole number." % name)


def as_float(value, name, positive=True):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ApiError("'%s' must be a number." % name)
    if positive and number <= 0:
        raise ApiError("'%s' must be greater than zero." % name)
    if number < 0:
        raise ApiError("'%s' cannot be negative." % name)
    return number


def paginate(model, domain, order=None):
    """Search ``model`` (as the salesman) one page at a time."""
    page = max(int_param('page', 1), 1)
    limit = min(max(int_param('limit', DEFAULT_LIMIT), 1), MAX_LIMIT)
    total = model.search_count(domain)
    records = model.search(domain, offset=(page - 1) * limit, limit=limit,
                           order=order)
    return records, {
        'page': page,
        'limit': limit,
        'total': total,
        'has_next': page * limit < total,
    }


def get_own(model_name, record_id, domain=None):
    """One record the salesman may see, or 404.

    Searching (rather than browsing) applies his record rules, so another
    salesman's record answers exactly like one that does not exist.
    """
    record = request.env[model_name].search(
        [('id', '=', as_int(record_id, 'id'))] + (domain or []), limit=1)
    if not record:
        raise ApiError("Record not found.", 404)
    return record


# ---------------------------------------------------------------------------
# The salesman and his van
# ---------------------------------------------------------------------------
def me():
    return request.env.user


def my_van(required=True):
    van = request.env['fleet.vehicle']._van_sales_van_of(me())
    if not van and required:
        raise ApiError("No sales van is assigned to you.", 409)
    if van and required and not van.van_location_id:
        raise ApiError("Your van has no stock location yet.", 409)
    return van.with_env(request.env) if van else van


def user_tz():
    try:
        return pytz.timezone(request.env.user.tz or 'UTC')
    except pytz.UnknownTimeZoneError:
        return pytz.utc


def today():
    return fields.Date.context_today(request.env.user)


def day_bounds_utc(date_from=None, date_to=None):
    """UTC naive datetimes covering whole local days, for datetime fields."""
    tz = user_tz()
    start = end = None
    if date_from:
        start = tz.localize(datetime.combine(date_from, time.min)) \
            .astimezone(pytz.utc).replace(tzinfo=None)
    if date_to:
        end = tz.localize(datetime.combine(date_to + timedelta(days=1), time.min)) \
            .astimezone(pytz.utc).replace(tzinfo=None)
    return start, end


def datetime_domain(field_name, date_from=None, date_to=None):
    start, end = day_bounds_utc(date_from, date_to)
    domain = []
    if start:
        domain.append((field_name, '>=', start))
    if end:
        domain.append((field_name, '<', end))
    return domain


def date_domain(field_name, date_from=None, date_to=None):
    domain = []
    if date_from:
        domain.append((field_name, '>=', date_from))
    if date_to:
        domain.append((field_name, '<=', date_to))
    return domain


# ---------------------------------------------------------------------------
# Serialising - Odoo's False becomes null, nothing else is added
# ---------------------------------------------------------------------------
def s(value):
    return value or None


def num(value, digits=None):
    value = value or 0.0
    return round(value, digits) if digits is not None else value


def money(value, currency=None):
    currency = currency or request.env.company.currency_id
    return currency.round(value or 0.0)


def ref(record, name_field='display_name'):
    if not record:
        return None
    return {'id': record.id, 'name': record[name_field] or ''}


def fmt_date(value):
    return fields.Date.to_string(value) if value else None


def fmt_datetime(value):
    if not value:
        return None
    local = pytz.utc.localize(value).astimezone(user_tz())
    return local.strftime('%Y-%m-%d %H:%M:%S')


def location_payload(location):
    if not location:
        return None
    return {'id': location.id, 'name': location.complete_name}


def van_payload(van):
    if not van:
        return None
    return {
        'id': van.id,
        'name': van.display_name,
        'plate': van.license_plate or None,
        'location': location_payload(van.van_location_id),
    }


def lines_payload(data, key='lines'):
    """Validate ``[{product_id, qty}]`` and return ``[(product, qty)]``."""
    lines = data.get(key)
    if not isinstance(lines, list) or not lines:
        raise ApiError("'%s' must be a non-empty list." % key)
    Product = request.env['product.product']
    result = []
    for index, line in enumerate(lines, start=1):
        if not isinstance(line, dict):
            raise ApiError("Line %s must be an object." % index)
        product_id = as_int(line.get('product_id'), 'product_id')
        qty = as_float(line.get('qty'), 'qty')
        product = Product.search([('id', '=', product_id)], limit=1)
        if not product:
            raise ApiError("Line %s: product %s not found." % (index, product_id), 404)
        result.append((product, qty))
    return result
