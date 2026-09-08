# Part of the Van Sales project.
{
    'name': "Van Sales - Mobile API",
    'summary': "Offline-first REST API for the Van Sales mobile application",
    'description': """
Van Sales - Mobile API
======================

REST API for the Flutter van sales application, following the same
architecture as the Red Ladder mobile API - ``/api/v1/`` routes, hashed bearer
tokens, one JSON envelope, a full request/response log, and Firebase push -
with the one thing van sales needs that Red Ladder never did: an **offline
sync layer**.

The requirement document is explicit that the app must work for a full working
day with no connectivity (§5.2 [M], §7), so the API is built around pull/push
rather than live reads:

* ``/sync/bootstrap`` - full scoped dataset plus the field schema
* ``/sync/pull`` - only what changed since the device's watermark
* ``/sync/push`` - batched, per-record results, idempotent on a client UUID
* ``/sync/filter-local`` - which of the ids a device holds no longer exist

Idempotency is the point: a device that loses the reply and re-sends a batch
must never create a second order. Every pushed record carries a UUID the
device generated, and the server records it before acting.
""",
    'author': "BizTech Computers",
    'website': "https://biztechbh.biz/",
    'category': 'Services/API',
    'version': '19.0.1.0.0',
    'license': 'OPL-1',
    'depends': [
        'van_sales_sale',
    ],
    # firebase_admin is deliberately NOT declared as a hard external
    # dependency. Odoo refuses to load a module whose external dependency is
    # missing, and the API - the whole point of this module - must not be
    # blocked by an optional push library. The import is guarded instead, and
    # push degrades with a clear log line. Install it with
    # ``pip install firebase-admin`` to enable notifications.
    'data': [
        'security/ir.model.access.csv',
        'security/van_sales_api_security.xml',
        'data/van_sales_api_data.xml',
        'views/van_sales_api_log_views.xml',
        'views/van_sales_device_views.xml',
        'views/van_sales_sync_log_views.xml',
        'views/van_sales_notification_views.xml',
        'views/van_sales_api_menus.xml',
    ],
    'installable': True,
    'application': False,
}
