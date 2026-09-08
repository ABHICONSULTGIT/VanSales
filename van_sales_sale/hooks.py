# Part of the Van Sales project.

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Give every existing sales van its delivery route.

    New vans get one on creation. Vans that already exist when this module is
    installed would otherwise have no route, and their sale orders would ship
    from the warehouse instead of the van - silently, because Odoo would simply
    fall back to the warehouse's own delivery rule.
    """
    vans = env['fleet.vehicle'].search([
        ('is_sales_van', '=', True),
        ('van_location_id', '!=', False),
        ('van_delivery_route_id', '=', False),
    ])
    provisioned = 0
    for van in vans:
        try:
            if van._van_sales_provision_delivery_route():
                provisioned += 1
        except Exception:            # noqa: BLE001 - never block an install
            _logger.exception(
                "van_sales_sale: could not provision a delivery route for %s",
                van.display_name)
    if provisioned:
        _logger.info(
            "van_sales_sale: provisioned %s van delivery route(s).", provisioned)
