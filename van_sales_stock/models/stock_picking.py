# Part of the Van Sales project.

from odoo import _, api, fields, models


class StockPicking(models.Model):
    """Recognise van loads and returns among ordinary internal transfers.

    Deliberately no separate "van load" document. A van load *is* an Odoo
    internal transfer from the warehouse to the van's location; wrapping it in
    a parallel model would duplicate state and lose standard valuation,
    traceability and reporting. Instead the transfer is classified from its own
    source and destination locations, so a transfer the office raises the
    normal way is picked up with no extra process to learn.
    """

    _inherit = 'stock.picking'

    van_src_id = fields.Many2one(
        comodel_name='fleet.vehicle', string="From Van",
        compute='_compute_van_fields', store=True, index='btree_not_null')
    van_dest_id = fields.Many2one(
        comodel_name='fleet.vehicle', string="To Van",
        compute='_compute_van_fields', store=True, index='btree_not_null')
    van_id = fields.Many2one(
        comodel_name='fleet.vehicle', string="Van",
        compute='_compute_van_fields', store=True, index='btree_not_null',
        help="The van this transfer concerns: the destination van for a load, "
             "the source van for a return.")
    van_operation = fields.Selection(
        selection=[
            ('load', "Van Load"),
            ('unload', "Van Return"),
            ('van_transfer', "Van to Van"),
            ('delivery', "Van Delivery"),
        ],
        string="Van Operation",
        compute='_compute_van_fields', store=True, index='btree_not_null')
    van_salesman_user_id = fields.Many2one(
        comodel_name='res.users', string="Salesman",
        related='van_id.salesman_user_id', store=True,
        index='btree_not_null')
    van_discrepancy_qty = fields.Float(
        string="Discrepancy", compute='_compute_van_discrepancy',
        digits='Product Unit',
        help="Total done quantity minus total demanded quantity. Negative is "
             "a short receipt, positive an over receipt.")
    van_has_discrepancy = fields.Boolean(
        string="Has Discrepancy", compute='_compute_van_discrepancy',
        store=True)
    van_reconciliation_id = fields.Many2one(
        comodel_name='van.sales.reconciliation', string="From Reconciliation",
        readonly=True, copy=False, index='btree_not_null',
        help="The stock reconciliation this return was raised from.")
    van_discrepancy_note = fields.Char(
        string="Discrepancy Reason",
        help="Why the quantity received differs from the quantity sent. Free "
             "text for now; a reason code list can be added once the client "
             "supplies the codes.")

    # --------------------------------------------------------------------
    # Compute
    # --------------------------------------------------------------------
    @api.depends('location_id', 'location_dest_id', 'location_dest_id.usage')
    def _compute_van_fields(self):
        locations = self.location_id | self.location_dest_id
        van_by_location = self.env['stock.location']._van_sales_vans_by_location(
            locations)
        empty = self.env['fleet.vehicle']
        for picking in self:
            src = van_by_location.get(picking.location_id.id, empty)
            dest = van_by_location.get(picking.location_dest_id.id, empty)
            picking.van_src_id = src
            picking.van_dest_id = dest
            if src and dest:
                picking.van_operation = 'van_transfer'
                picking.van_id = dest
            elif dest:
                picking.van_operation = 'load'
                picking.van_id = dest
            elif src:
                # Stock leaving a van for a CUSTOMER location is a delivery,
                # not a return. Without this a van sale would file itself under
                # Van Returns, and the warehouse would think the goods were
                # coming back.
                picking.van_operation = (
                    'delivery'
                    if picking.location_dest_id.usage == 'customer'
                    else 'unload')
                picking.van_id = src
            else:
                picking.van_operation = False
                picking.van_id = empty

    @api.depends('van_operation', 'state', 'move_ids.quantity',
                 'move_ids.product_uom_qty')
    def _compute_van_discrepancy(self):
        """Short or over receipt, in the product's own unit of measure.

        Only meaningful once the transfer is done: before that the gap between
        demand and done quantity is just work in progress.
        """
        for picking in self:
            discrepancy = 0.0
            if picking.van_operation and picking.state == 'done':
                for move in picking.move_ids:
                    if move.state == 'cancel':
                        continue
                    uom = move.product_uom
                    product_uom = move.product_id.uom_id
                    done = uom._compute_quantity(
                        move.quantity, product_uom, round=False)
                    demand = uom._compute_quantity(
                        move.product_uom_qty, product_uom, round=False)
                    discrepancy += done - demand
            picking.van_discrepancy_qty = discrepancy
            picking.van_has_discrepancy = bool(
                picking.van_operation and picking.state == 'done'
                and abs(discrepancy) > 1e-6)

    # --------------------------------------------------------------------
    # Actions
    # --------------------------------------------------------------------
    def action_van_sales_view_van(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Van"),
            'res_model': 'fleet.vehicle',
            'view_mode': 'form',
            'res_id': self.van_id.id,
        }
