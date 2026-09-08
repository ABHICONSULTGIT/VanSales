# Part of the Van Sales project.

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Turn on multi-location stock, which van sales cannot work without.

    Every van is a stock location, so ``stock.group_stock_multi_locations`` is
    not optional here: without it Odoo hides the source and destination fields
    on transfers, and - the part that actually breaks things - each warehouse's
    internal operation type is created **archived**
    (``stock.warehouse._get_picking_type_create_values`` sets
    ``'active': self.env.user.has_group('stock.group_stock_multi_locations')``),
    so there is no operation type to raise a van load against.

    This mirrors exactly what ticking Storage Locations in the Inventory
    settings does - see ``stock/models/res_config_settings.py.set_values`` -
    namely add the group to ``base.group_user`` and reactivate the internal
    operation types.
    """
    location_group = env.ref('stock.group_stock_multi_locations',
                             raise_if_not_found=False)
    base_user = env.ref('base.group_user', raise_if_not_found=False)
    if not location_group or not base_user:
        _logger.warning(
            "van_sales_stock: could not resolve the stock multi-location "
            "group; enable Storage Locations by hand in Inventory settings.")
        return

    if location_group not in base_user.implied_ids:
        base_user.sudo().write({'implied_ids': [(4, location_group.id)]})
        _logger.info("van_sales_stock: enabled Storage Locations.")

    # Warehouses created while the group was off carry an archived internal
    # operation type. Reactivate them, as the Inventory setting does.
    warehouses = env['stock.warehouse'].with_context(active_test=True).search([])
    archived = warehouses.int_type_id.filtered(lambda t: not t.active)
    if archived:
        archived.sudo().write({'active': True})
        _logger.info(
            "van_sales_stock: reactivated %s internal operation type(s).",
            len(archived))
