# Part of the Van Sales project.

from odoo import _, http
from odoo.http import request

from .base import (ErrCode, current_user, error_response, get_json_body,
                   get_query_int, paginate, success_response, token_required,
                   _b, _dt, _i, _s)


class VanSalesNotificationController(http.Controller):

    @http.route('/api/v1/notifications', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    def list_notifications(self, **kw):
        records, pagination = paginate(
            'van.sales.notification',
            [('user_id', '=', current_user().id)],
            page=get_query_int('page', 1),
            limit=get_query_int('limit', 50),
            order='create_date desc, id desc')
        return success_response(
            data=[{
                'id': _i(n.id),
                'title': _s(n.title),
                'body': _s(n.body),
                'type': _s(n.notification_type) or 'system',
                'is_read': _b(n.is_read),
                'res_model': _s(n.res_model),
                'res_id': _i(n.res_id),
                'created_at': _dt(n.create_date),
            } for n in records],
            pagination=pagination)

    @http.route('/api/v1/notifications/unread-count', type='http',
                auth='public', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    def unread_count(self, **kw):
        count = request.env['van.sales.notification'].sudo().search_count([
            ('user_id', '=', current_user().id), ('is_read', '=', False),
        ])
        return success_response(data={'unread_count': _i(count)})

    @http.route('/api/v1/notifications/read', type='http', auth='public',
                methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    @token_required
    def mark_read(self, **kw):
        body = get_json_body()
        ids = body.get('notification_ids') or []
        Notification = request.env['van.sales.notification'].sudo()
        domain = [('user_id', '=', current_user().id), ('is_read', '=', False)]
        if body.get('mark_all'):
            records = Notification.search(domain)
        elif ids:
            records = Notification.search(
                domain + [('id', 'in', [int(i) for i in ids])])
        else:
            return error_response(
                _("Send notification_ids, or mark_all."),
                status=400, code=ErrCode.VALIDATION)
        records.write({'is_read': True})
        return success_response(data={'marked': len(records)})
