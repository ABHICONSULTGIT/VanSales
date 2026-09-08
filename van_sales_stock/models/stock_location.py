# Part of the Van Sales project.

from odoo import api, models


class StockLocation(models.Model):
    _inherit = 'stock.location'

    @api.model
    def _van_sales_vans_by_location(self, locations):
        """Map each location to the sales van that owns it, if any.

        A location belongs to a van when the van's stock location is that
        location or one of its ancestors, so a sub-location inside a van still
        resolves to the van. ``parent_path`` already holds the ancestor chain,
        so this costs one search regardless of how many locations are passed.

        :return: ``{location_id: fleet.vehicle recordset}``, only for locations
                 that resolve to a van.
        """
        Vehicle = self.env['fleet.vehicle']
        if not locations:
            return {}
        ancestors_by_location = {}
        all_ancestor_ids = set()
        for location in locations:
            ids = [int(i) for i in (location.parent_path or '').split('/') if i]
            ancestors_by_location[location.id] = ids
            all_ancestor_ids.update(ids)
        if not all_ancestor_ids:
            return {}
        # sudo: resolving which van owns a location is a structural lookup, and
        # a salesman must not need read access to other vans to have their own
        # transfers classified correctly.
        vans = Vehicle.sudo().search([
            ('is_sales_van', '=', True),
            ('van_location_id', 'in', list(all_ancestor_ids)),
        ])
        van_by_location_id = {v.van_location_id.id: v for v in vans}
        result = {}
        for location_id, ancestor_ids in ancestors_by_location.items():
            for ancestor_id in reversed(ancestor_ids):   # nearest first
                van = van_by_location_id.get(ancestor_id)
                if van:
                    result[location_id] = van
                    break
        return result

    def _van_sales_owning_van(self):
        """The sales van owning this location, or an empty recordset."""
        self.ensure_one()
        return self._van_sales_vans_by_location(self).get(
            self.id, self.env['fleet.vehicle'])
