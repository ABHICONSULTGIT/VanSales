# Part of the Van Sales project.

from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

SUPERVISOR_GROUP = 'van_sales_base.group_van_sales_supervisor'


def _is_counter_only(env):
    """A salesman who may count but not correct what Odoo thinks it has."""
    return not env.su and not env.user.has_group(SUPERVISOR_GROUP)


class VanSalesReconciliation(models.Model):
    """Count what is physically on the van and correct Odoo to match.

    Three numbers per product: what Odoo thinks is on the van (System), what
    the counter found (Counted), and the difference. Applying turns the
    differences into an inventory adjustment on the van's location. Returning
    sends the counted stock back to the warehouse as an ordinary transfer.

    How the stock got there is not repeated here - the Van Movements button
    opens Odoo's own move history for the van on that day.
    """

    _name = 'van.sales.reconciliation'
    _inherit = ['mail.thread']
    _description = "Van Stock Reconciliation"
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string="Reference", required=True, copy=False, readonly=True,
        default=lambda self: _("New"))
    van_id = fields.Many2one(
        comodel_name='fleet.vehicle', string="Van", required=True,
        domain="[('is_sales_van', '=', True)]",
        check_company=True, ondelete='restrict', tracking=True,
        index=True)
    van_location_id = fields.Many2one(
        comodel_name='stock.location', string="Van Stock Location",
        related='van_id.van_location_id', store=True, readonly=True)
    salesman_user_id = fields.Many2one(
        comodel_name='res.users', string="Salesman",
        related='van_id.salesman_user_id', store=True,
        index='btree_not_null')
    company_id = fields.Many2one(
        comodel_name='res.company', string="Company", required=True,
        index=True, default=lambda self: self.env.company)
    date = fields.Date(
        string="Date", required=True, tracking=True,
        default=fields.Date.context_today)
    state = fields.Selection(
        selection=[
            ('draft', "Draft"),
            ('done', "Applied"),
        ],
        string="Status", default='draft', required=True,
        tracking=True, copy=False)
    user_id = fields.Many2one(
        comodel_name='res.users', string="Counted By",
        default=lambda self: self.env.user, tracking=True)
    line_ids = fields.One2many(
        comodel_name='van.sales.reconciliation.line',
        inverse_name='reconciliation_id', string="Lines")
    note = fields.Text(string="Notes")
    return_picking_id = fields.Many2one(
        comodel_name='stock.picking', string="Return Transfer",
        readonly=True, copy=False, check_company=True,
        help="Transfer sending the counted stock back to the warehouse.")

    _van_date_uniq = models.Constraint(
        'UNIQUE(name, company_id)',
        "A reconciliation with this reference already exists.",
    )

    # --------------------------------------------------------------------
    # Constraints
    # --------------------------------------------------------------------
    @api.constrains('van_id')
    def _check_van_location(self):
        for record in self:
            if record.van_id and not record.van_id.van_location_id:
                raise UserError(_(
                    "Van %s has no stock location, so its stock cannot be "
                    "reconciled.", record.van_id.display_name))

    # --------------------------------------------------------------------
    # ORM
    # --------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _("New")) == _("New"):
                company_id = vals.get('company_id') or self.env.company.id
                vals['name'] = self.env['ir.sequence'].with_company(
                    company_id).next_by_code(
                        'van.sales.reconciliation') or _("New")
        return super().create(vals_list)

    def write(self, vals):
        # A salesman may start a count and type what he found (D4); the
        # header itself - van, date, state, return - is not his to change.
        if _is_counter_only(self.env) and set(vals) - {'note'}:
            raise AccessError(_(
                "You can only enter counted quantities and a note on a stock "
                "count."))
        return super().write(vals)

    def unlink(self):
        blocked = self.filtered(lambda r: r.state == 'done')
        if blocked:
            raise UserError(_(
                "An applied reconciliation cannot be deleted, because the "
                "inventory adjustments it made are already in the stock "
                "history: %s",
                ", ".join(blocked.mapped('display_name'))))
        return super().unlink()

    # --------------------------------------------------------------------
    # Lines
    # --------------------------------------------------------------------
    def _van_location_ids(self):
        """The van location and everything under it."""
        self.ensure_one()
        return self.env['stock.location'].search(
            [('id', 'child_of', self.van_location_id.id)]).ids

    def action_generate_lines(self):
        """Load what Odoo thinks is on the van. Counted quantities are kept.

        A product that left the van since the last refresh drops to zero on
        the line rather than keeping a stale figure.
        """
        for record in self:
            if record.state != 'draft':
                raise UserError(_(
                    "%s is already applied, so its lines cannot be refreshed.",
                    record.display_name))
            record._generate_lines()
        return True

    def _generate_lines(self):
        """One grouped read of the van's quants.

        sudo: the counter must see everything on the van, including stock moved
        in by warehouse staff. Scoped strictly to this van's locations.
        """
        self.ensure_one()
        on_van = {
            product: quantity
            for product, quantity in self.env['stock.quant'].sudo()._read_group(
                [('location_id', 'in', self._van_location_ids())],
                ['product_id'], ['quantity:sum'])
        }
        existing = {line.product_id: line for line in self.line_ids}

        # sudo for the line writes: system quantities are Odoo's own figures,
        # which a salesman starting a count may not set himself (see the line
        # guard below). Confined to this count's lines.
        for product, line in existing.items():
            line.sudo().expected_qty = on_van.get(product, 0.0)

        new_lines = []
        for product, quantity in on_van.items():
            if product in existing or product.uom_id.is_zero(quantity):
                continue
            # Counted starts at the system quantity on purpose: an untouched
            # line then has no difference and adjusts nothing. Starting it at
            # zero would write off every product the counter did not get to.
            new_lines.append({
                'reconciliation_id': self.id,
                'product_id': product.id,
                'expected_qty': quantity,
                'counted_qty': quantity,
            })
        if new_lines:
            self.env['van.sales.reconciliation.line'].sudo().create(new_lines)

    # --------------------------------------------------------------------
    # Applying the count
    # --------------------------------------------------------------------
    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group(
                'van_sales_base.group_van_sales_manager'):
            raise AccessError(_(
                "Only a Van Sales Administrator can apply a stock "
                "reconciliation."))
        if self.state != 'draft':
            raise UserError(_("%s is already applied.", self.display_name))
        if not self.line_ids:
            raise UserError(_(
                "%s has no lines. Load the van's stock first.",
                self.display_name))

        adjusted = self._apply_differences()
        self.state = 'done'
        self.message_post(body=_(
            "Count applied. %(adjusted)s product(s) adjusted out of "
            "%(total)s counted.",
            adjusted=adjusted, total=len(self.line_ids)))
        return True

    def _apply_differences(self):
        """Write the counted quantities into stock as an inventory adjustment.

        ``_apply_inventory()`` rather than ``action_apply_inventory()``: the
        public method silently returns a wizard instead of applying when a
        quant is outdated - when something moved between counting and
        applying - which for a programmatic caller means nothing happens. The
        difference is recomputed against the live quantity first, which is the
        "keep counted quantity" resolution that wizard itself offers.

        sudo: applying an adjustment needs Inventory User, which a Van Sales
        Administrator does not necessarily hold. Gated on the manager group
        above, and every write is confined to this van's location.
        """
        self.ensure_one()
        Quant = self.env['stock.quant'].sudo().with_context(
            inventory_mode=True)
        adjusted = 0
        for line in self.line_ids:
            if line.product_id.uom_id.compare(
                    line.counted_qty, line.expected_qty) == 0:
                continue
            quant = Quant.create({
                'product_id': line.product_id.id,
                'location_id': self.van_location_id.id,
                'inventory_quantity': line.counted_qty,
            })
            quant.inventory_diff_quantity = line.counted_qty - quant.quantity
            quant._apply_inventory()
            adjusted += 1
        return adjusted

    # --------------------------------------------------------------------
    # Returning the counted stock to the warehouse
    # --------------------------------------------------------------------
    def action_create_return_picking(self):
        """Raise a draft transfer sending every counted quantity back.

        Draft, deliberately: it is an ordinary internal transfer, so whoever
        receives the goods adjusts any quantity that stays on the van and
        validates it there - no custom return column needed.
        """
        self.ensure_one()
        if not self.env.user.has_group(
                'van_sales_base.group_van_sales_manager'):
            raise AccessError(_(
                "Only a Van Sales Administrator can raise a van return."))
        if self.state != 'done':
            raise UserError(_(
                "Apply the count before returning stock."))
        if self.return_picking_id and self.return_picking_id.state != 'cancel':
            raise UserError(_(
                "%(name)s already has the return transfer %(picking)s. Cancel "
                "it first if you need to raise another.",
                name=self.display_name,
                picking=self.return_picking_id.display_name))
        lines = self.line_ids.filtered(
            lambda l: l.product_id.uom_id.compare(l.counted_qty, 0.0) > 0)
        if not lines:
            raise UserError(_("Nothing was counted on the van to return."))

        warehouse, picking_type = self.van_id._van_sales_internal_picking_type()
        destination = warehouse.lot_stock_id
        # No 'name' key on the moves: stock.move has no such field in Odoo 19.
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': self.van_location_id.id,
            'location_dest_id': destination.id,
            'origin': self.name,
            'company_id': self.company_id.id,
            'van_reconciliation_id': self.id,
            'move_ids': [(0, 0, {
                'product_id': line.product_id.id,
                'product_uom_qty': line.counted_qty,
                'product_uom': line.product_id.uom_id.id,
                'location_id': self.van_location_id.id,
                'location_dest_id': destination.id,
                'company_id': self.company_id.id,
            }) for line in lines],
        })
        self.return_picking_id = picking
        self.message_post(body=_(
            "Draft return transfer %(picking)s raised for %(count)s "
            "product(s).", picking=picking.display_name, count=len(lines)))
        return self.action_view_return_picking()

    def action_view_return_picking(self):
        self.ensure_one()
        if not self.return_picking_id:
            raise UserError(_("%s has no return transfer.", self.display_name))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Van Return"),
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': self.return_picking_id.id,
        }

    def action_view_moves(self):
        """Every movement in or out of the van on the reconciliation date.

        The day is cut in the same timezone ``fields.Date.context_today`` used
        to fill the date - the context's first, then the user's - so the two
        always agree on where midnight falls.
        """
        self.ensure_one()
        tz = pytz.timezone(
            self.env.context.get('tz') or self.env.user.tz or 'UTC')
        start = tz.localize(datetime.combine(self.date, time.min)) \
            .astimezone(pytz.utc).replace(tzinfo=None)
        end = start + timedelta(days=1)
        location_ids = self._van_location_ids()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Van Movements"),
            'res_model': 'stock.move.line',
            'view_mode': 'list,form',
            'domain': [
                ('state', '=', 'done'),
                ('date', '>=', start),
                ('date', '<', end),
                '|',
                ('location_id', 'in', location_ids),
                ('location_dest_id', 'in', location_ids),
            ],
        }


class VanSalesReconciliationLine(models.Model):
    _name = 'van.sales.reconciliation.line'
    _description = "Van Stock Reconciliation Line"
    _order = 'reconciliation_id, product_id, id'
    _check_company_auto = True

    reconciliation_id = fields.Many2one(
        comodel_name='van.sales.reconciliation', string="Reconciliation",
        required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one(
        comodel_name='product.product', string="Product",
        required=True, index=True, check_company=True, ondelete='restrict')
    product_uom_id = fields.Many2one(
        comodel_name='uom.uom', string="Unit",
        related='product_id.uom_id', readonly=True)
    company_id = fields.Many2one(
        comodel_name='res.company', related='reconciliation_id.company_id',
        store=True, index=True)
    expected_qty = fields.Float(
        string="System", digits='Product Unit', readonly=True,
        help="What Odoo believes is on the van.")
    counted_qty = fields.Float(
        string="Counted", digits='Product Unit',
        help="Starts at the system quantity, so a line you do not touch "
             "adjusts nothing. Change only what you counted differently.")
    difference_qty = fields.Float(
        string="Difference", digits='Product Unit',
        compute='_compute_difference_qty', store=True,
        help="Counted minus system. Negative means stock is missing.")

    _product_reconciliation_uniq = models.Constraint(
        'UNIQUE(reconciliation_id, product_id)',
        "This product is already on this reconciliation.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        # A salesman may add a product he found that Odoo does not know is on
        # the van - at a system quantity of zero, never more.
        if _is_counter_only(self.env) and any(
                vals.get('expected_qty') for vals in vals_list):
            raise AccessError(_(
                "The system quantity on a stock count is filled in by Odoo."))
        return super().create(vals_list)

    def write(self, vals):
        if _is_counter_only(self.env) and set(vals) - {'counted_qty'}:
            raise AccessError(_(
                "You can only enter the counted quantity on a stock count."))
        return super().write(vals)

    @api.depends('counted_qty', 'expected_qty')
    def _compute_difference_qty(self):
        for line in self:
            line.difference_qty = line.counted_qty - line.expected_qty
