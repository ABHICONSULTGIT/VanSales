# Part of the Van Sales project.
"""19.0.1.x -> 19.0.2.0.0: remove the route record rules.

Routes are now shared checklists with no van or salesman of their own, so the
"own routes only" / "all routes" rules went away with those fields. They were
declared ``noupdate``, and Odoo never deletes a ``noupdate`` record on upgrade
just because it left the XML - they would survive with a domain on the removed
``salesman_user_id`` and make every route read by a salesman fail. Hence the
explicit removal here, on upgrade only.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

OBSOLETE_RULES = (
    'van_sales_base.van_sales_route_own_rule',
    'van_sales_base.van_sales_route_all_rule',
    'van_sales_base.van_sales_route_line_own_rule',
    'van_sales_base.van_sales_route_line_all_rule',
)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    removed = []
    for xmlid in OBSOLETE_RULES:
        rule = env.ref(xmlid, raise_if_not_found=False)
        if rule:
            rule.unlink()
            removed.append(xmlid)
    _logger.info("van_sales_base: removed obsolete record rules %s", removed)
