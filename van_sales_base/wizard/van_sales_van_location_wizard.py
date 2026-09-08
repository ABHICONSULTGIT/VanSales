# Part of the Van Sales project.

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class VanSalesVanLocationWizard(models.TransientModel):
    """Provision van stock locations for existing vehicles.

    New sales vans get their location automatically on creation. This wizard
    remains for the cases automation deliberately does not cover: vehicles
    created before this module, vehicles whose warehouse could not be resolved
    at creation time, and bulk provisioning into a warehouse other than the
    vehicle's own.
    """

    _name = 'van.sales.van.location.wizard'
    _description = "Create Van Stock Locations"

    warehouse_id = fields.Many2one(
        comodel_name='stock.warehouse', string="Warehouse",
        required=True, default=lambda self: self._default_warehouse_id(),
        help="The van locations are created under this warehouse, so the "
             "vans' stock stays inside it for reporting and valuation.")
    company_id = fields.Many2one(
        comodel_name='res.company', related='warehouse_id.company_id',
        string="Company")
    vehicle_ids = fields.Many2many(
        comodel_name='fleet.vehicle', string="Vehicles", required=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    parent_location_id = fields.Many2one(
        comodel_name='stock.location', string="Parent Location",
        compute='_compute_parent_location_id',
        help="Existing parent location the van locations will be created "
             "under. Empty means it does not exist yet and will be created.")
    vehicle_todo_count = fields.Integer(
        string="To Provision", compute='_compute_vehicle_todo_count')
    vehicle_done_count = fields.Integer(
        string="Already Provisioned", compute='_compute_vehicle_todo_count')

    # --------------------------------------------------------------------
    # Defaults
    # --------------------------------------------------------------------
    @api.model
    def _default_warehouse_id(self):
        return self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if 'vehicle_ids' in fields_list and not values.get('vehicle_ids'):
            context = self.env.context
            if context.get('active_model') == 'fleet.vehicle':
                active_ids = context.get('active_ids') or []
                if active_ids:
                    values['vehicle_ids'] = [(6, 0, list(active_ids))]
        return values

    # --------------------------------------------------------------------
    # Compute
    # --------------------------------------------------------------------
    @api.depends('warehouse_id')
    def _compute_parent_location_id(self):
        Location = self.env['stock.location']
        for wizard in self:
            view_location = wizard.warehouse_id.view_location_id
            wizard.parent_location_id = Location.sudo().with_context(
                active_test=False).search([
                    ('location_id', '=', view_location.id),
                    ('name', '=', 'Vans'),
                ], limit=1) if view_location else Location

    @api.depends('vehicle_ids.van_location_id')
    def _compute_vehicle_todo_count(self):
        for wizard in self:
            done = wizard.vehicle_ids.filtered(lambda v: v.van_location_id)
            wizard.vehicle_done_count = len(done)
            wizard.vehicle_todo_count = len(wizard.vehicle_ids) - len(done)

    # --------------------------------------------------------------------
    # Action
    # --------------------------------------------------------------------
    def action_create_locations(self):
        self.ensure_one()
        if not self.env.user.has_group(
                'van_sales_base.group_van_sales_manager'):
            raise AccessError(_(
                "Only a Van Sales Administrator can provision van stock "
                "locations."))

        todo = self.vehicle_ids.filtered(lambda v: not v.van_location_id)
        if not todo:
            raise UserError(_(
                "Every selected vehicle already has a van stock location. "
                "Nothing to do."))

        for vehicle in todo:
            vehicle._van_sales_provision_location(warehouse=self.warehouse_id)

        return {
            'type': 'ir.actions.act_window',
            'name': _("Sales Vans"),
            'res_model': 'fleet.vehicle',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.vehicle_ids.ids)],
        }
