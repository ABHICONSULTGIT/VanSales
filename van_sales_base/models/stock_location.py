# Part of the Van Sales project.

from odoo import _, api, fields, models
from odoo.exceptions import UserError

VAN_PARENT_LOCATION_NAME = "Vans"


class StockLocation(models.Model):
    _inherit = 'stock.location'

    van_vehicle_ids = fields.One2many(
        comodel_name='fleet.vehicle',
        inverse_name='van_location_id',
        string="Sales Vans",
        help="Sales vans whose stock is held in this location. The link is "
             "kept on the vehicle so the location stays the authoritative "
             "anchor for stock, and a vehicle can be swapped without moving "
             "any stock.")

    @api.model
    def _van_sales_vans_parent(self, warehouse):
        """Return '<Warehouse> / Vans', creating it the first time.

        A view location: it groups the van locations without ever holding
        stock itself (``stock.quant`` forbids quants in a view location).

        sudo: creating a stock location requires Inventory Administrator,
        which a Van Sales Administrator does not necessarily hold. The
        operation is tightly bounded - one fixed name, one fixed parent, one
        fixed usage - and the callers are the van provisioning paths only.
        """
        if not warehouse:
            return self.browse()
        view_location = warehouse.view_location_id
        if not view_location:
            raise UserError(_(
                "Warehouse %s has no view location, so van locations cannot "
                "be created under it.", warehouse.display_name))
        Location = self.sudo().with_context(active_test=False)
        parent = Location.search([
            ('location_id', '=', view_location.id),
            ('name', '=', VAN_PARENT_LOCATION_NAME),
        ], limit=1)
        if parent:
            return parent
        return Location.create({
            'name': VAN_PARENT_LOCATION_NAME,
            'usage': 'view',
            'location_id': view_location.id,
            'company_id': warehouse.company_id.id,
        })
