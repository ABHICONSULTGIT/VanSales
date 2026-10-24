# Part of the Van Sales project.

from odoo import http
from odoo.http import request

from .base import (
    API_PREFIX, date_domain, date_param, fmt_date, get_own, me, money, ok,
    paginate, ref, token_required, today,
)


def order_brief(order):
    if not order:
        return None
    return {'id': order.id, 'name': order.name, 'state': order.state,
            'amount': money(order.amount_total, order.currency_id)}


def place_payload(location):
    if not location:
        return None
    return {'id': location.id, 'name': location.display_name,
            'latitude': location.latitude or None,
            'longitude': location.longitude or None}


def visit_line(visit):
    return {
        'id': visit.id,
        'sequence': visit.sequence,
        'customer': ref(visit.partner_id),
        'stop_location': place_payload(visit.stop_location_id),
        # sudo: the line is on his own plan, but the office may have keyed
        # its order under another salesperson, which his own-documents rule
        # hides. Only the order's number, state and amount are shown.
        'order': order_brief(visit.sale_order_id.sudo()),
        # Decision D3: a stop is done when it carries an active order.
        'done': bool(visit.sale_order_id),
    }


def plan_summary(plan):
    visits = plan.visit_ids
    return {
        'id': plan.id,
        'date': fmt_date(plan.date),
        'route': ref(plan.route_id),
        'stops': len(visits),
        'sold': len(visits.filtered('sale_order_id')),
    }


def plan_detail(plan):
    return {
        'id': plan.id,
        'date': fmt_date(plan.date),
        'route': ref(plan.route_id),
        'visits': [visit_line(v) for v in plan.visit_ids.sorted(
            lambda v: (v.sequence, v.id))],
    }


def todays_plan():
    return request.env['van.sales.visit.plan'].search([
        ('salesman_user_id', '=', me().id), ('date', '=', today()),
    ], limit=1)


class VanSalesVisitController(http.Controller):

    @http.route(API_PREFIX + '/visit-plans/today', type='http', auth='public',
                methods=['GET'], csrf=False, cors='*')
    @token_required
    def today(self, **kw):
        plan = todays_plan()
        if not plan:
            return ok(None, "No visit plan yet today. The first order of the "
                            "day creates it.")
        return ok(plan_detail(plan))

    @http.route(API_PREFIX + '/visit-plans', type='http', auth='public',
                methods=['GET'], csrf=False, cors='*')
    @token_required
    def history(self, **kw):
        domain = [('salesman_user_id', '=', me().id)] + date_domain(
            'date', date_param('date_from'), date_param('date_to'))
        plans, page = paginate(request.env['van.sales.visit.plan'], domain,
                               order='date desc, id desc')
        return ok([plan_summary(p) for p in plans], pagination=page)

    @http.route(API_PREFIX + '/visit-plans/<int:plan_id>', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    @token_required
    def detail(self, plan_id, **kw):
        plan = get_own('van.sales.visit.plan', plan_id,
                       [('salesman_user_id', '=', me().id)])
        return ok(plan_detail(plan))

    @http.route(API_PREFIX + '/visits/<int:visit_id>', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    @token_required
    def visit(self, visit_id, **kw):
        visit = get_own('van.sales.visit', visit_id,
                        [('salesman_user_id', '=', me().id)])
        partner = visit.partner_id
        route_line = visit.plan_id.route_id.line_ids.filtered(
            lambda l: (l.partner_id == partner) if partner
            else (l.stop_location_id == visit.stop_location_id))[:1]
        data = visit_line(visit)
        data.update({
            'plan_id': visit.plan_id.id,
            'date': fmt_date(visit.date),
            'customer': {
                'id': partner.id, 'name': partner.display_name,
                'phone': partner.phone or None,
                'street': partner.street or None, 'city': partner.city or None,
                'latitude': partner.partner_latitude or None,
                'longitude': partner.partner_longitude or None,
            } if partner else None,
            'instruction': route_line.instruction or None,
        })
        return ok(data)
