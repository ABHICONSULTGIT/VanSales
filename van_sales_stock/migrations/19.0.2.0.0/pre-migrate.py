# Part of the Van Sales project.
"""19.0.1.x -> 19.0.2.0.0: reconciliation keeps one date instead of a period.

Runs before the ORM touches the table, so:

* ``date`` is created and filled from the old period's end (``date_to``) as
  that day was in the counter's timezone. Without this the ORM would stamp
  every existing count with the day of the upgrade.
* ``cancel`` is gone. Old cancel was only allowed from draft - nothing was ever
  applied - and its "Reset to Draft" brought the count straight back, so a
  cancelled count becomes a draft again. Nothing is adjusted until someone
  presses Apply, and a draft can be deleted.

The old ``date_from`` / ``date_to`` columns are dropped by the ORM at the end
of the upgrade, as for every removed field.
"""

import logging

import pytz

_logger = logging.getLogger(__name__)


def _column_exists(cr, table, column):
    cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s", (table, column))
    return bool(cr.fetchone())


def migrate(cr, version):
    if not version or not _column_exists(cr, 'van_sales_reconciliation', 'id'):
        return

    if not _column_exists(cr, 'van_sales_reconciliation', 'date'):
        cr.execute("ALTER TABLE van_sales_reconciliation ADD COLUMN date date")

    stamp = ("COALESCE(r.date_to, r.create_date)"
             if _column_exists(cr, 'van_sales_reconciliation', 'date_to')
             else "r.create_date")
    cr.execute(f"""
        SELECT r.id, {stamp}, p.tz
          FROM van_sales_reconciliation r
     LEFT JOIN res_users u ON u.id = COALESCE(r.user_id, r.create_uid)
     LEFT JOIN res_partner p ON p.id = u.partner_id
         WHERE r.date IS NULL
    """)
    filled = 0
    for rec_id, stamp_value, tz_name in cr.fetchall():
        if not stamp_value:
            continue
        try:
            tz = pytz.timezone(tz_name or 'UTC')
        except pytz.UnknownTimeZoneError:
            tz = pytz.utc
        day = pytz.utc.localize(stamp_value).astimezone(tz).date()
        cr.execute("UPDATE van_sales_reconciliation SET date = %s WHERE id = %s",
                   (day, rec_id))
        filled += 1

    cr.execute("UPDATE van_sales_reconciliation SET state = 'draft' "
               "WHERE state = 'cancel'")
    reopened = cr.rowcount
    _logger.info(
        "van_sales_stock: dated %s existing reconciliation(s), returned %s "
        "cancelled one(s) to draft.", filled, reopened)
