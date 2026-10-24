# Part of the Van Sales project.

from odoo import http
from odoo.http import request

from .base import (
    API_PREFIX, datetime_domain, me, money, my_van, ok, today,
    token_required, van_payload,
)
from .customer_controller import my_customers_domain
from .visit_controller import plan_summary, todays_plan

LOW_STOCK_QTY = 5.0


def _sales(date_from, date_to):
    [(count, amount)] = request.env['sale.order']._read_group(
        [('user_id', '=', me().id), ('state', '=', 'sale')]
        + datetime_domain('date_order', date_from, date_to),
        [], ['__count', 'amount_total:sum'])
    return count, money(amount)


class VanSalesDashboardController(http.Controller):

    @http.route(API_PREFIX + '/dashboard', type='http', auth='public',
                methods=['GET'], csrf=False, cors='*')
    @token_required
    def dashboard(self, **kw):
        user = me()
        van = my_van(required=False)
        day = today()

        stock = None
        if van and van.van_location_id:
            on_van = [q for q in van._van_sales_available_quantities().values()
                      if q > 0]
            stock = {
                'products': len(on_van),
                'total_qty': sum(on_van),
                'low_stock_products': len([q for q in on_van
                                           if q <= LOW_STOCK_QTY]),
            }

        # sudo: balances include invoices the office raised; his customers only.
        customers = request.env['res.partner'].search(my_customers_domain())
        dues = [c.credit for c in customers.sudo() if c.credit > 0]

        plan = todays_plan()
        recent = request.env['van.sales.visit.plan'].search(
            [('salesman_user_id', '=', user.id), ('date', '<', day)],
            order='date desc, id desc', limit=5)

        today_orders, today_amount = _sales(day, day)
        month_orders, month_amount = _sales(day.replace(day=1), day)
        [(collected,)] = request.env['van.sales.collection']._read_group(
            [('salesman_user_id', '=', user.id), ('state', '=', 'posted'),
             ('date', '=', day)], [], ['amount_total:sum'])
        open_invoices = request.env['account.move'].search_count([
            ('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('invoice_user_id', '=', user.id)])

        return ok({
            'van': van_payload(van),
            'stock': stock,
            'customers': {
                'assigned': len(customers),
                'with_balance_due': len(dues),
                'total_due': money(sum(dues)),
            },
            'today': plan_summary(plan) if plan else None,
            'sales': {
                'today_orders': today_orders,
                'today_amount': today_amount,
                'month_orders': month_orders,
                'month_amount': month_amount,
                'today_collected': money(collected),
                'open_invoices': open_invoices,
            },
            'recent_plans': [plan_summary(p) for p in recent],
        })
