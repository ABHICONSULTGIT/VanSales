# Part of the Van Sales project.

from collections import defaultdict

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

# Movement buckets, keyed by the usage of the location on the other side.
IN_BUCKETS = {'internal': 'in_load_qty', 'transit': 'in_load_qty'}
OUT_BUCKETS = {
    'customer': 'out_sale_qty',
    'internal': 'out_return_qty',
    'transit': 'out_return_qty',
    'inventory': 'out_adjust_qty',
}
QTY_FIELDS = (
    'in_load_qty', 'in_other_qty', 'out_sale_qty', 'out_return_qty',
    'out_adjust_qty', 'out_other_qty', 'expected_qty',
)


class VanSalesReconciliation(models.Model):
    """Counted van stock against system van stock, with the movements that
    explain the difference.

    Computed from ``stock.move``, not from sales documents. That matters twice
    over: it is correct today with no sales module installed, and once
    *Van Sales - Sale* exists its deliveries appear in the "Sold" column
    automatically, with nothing to wire up.

    The requirement document states the reconciliation as
    ``opening + loaded - sold - returned - FOC = expected closing``. Free-of-
    charge lines are not split out here: FOC and a normal sale both move stock
    to a customer location and are indistinguishable at the stock-move level.
    The split needs the FOC flag, which lives in the sales module.
    """

    _name = 'van.sales.reconciliation'
    _inherit = ['mail.thread']
    _description = "Van Stock Reconciliation"
    _order = 'date_to desc, id desc'
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
    date_from = fields.Datetime(
        string="From", required=True, tracking=True,
        default=lambda self: self._default_date_from())
    date_to = fields.Datetime(
        string="To", required=True, tracking=True,
        default=fields.Datetime.now)
    state = fields.Selection(
        selection=[
            ('draft', "Draft"),
            ('done', "Applied"),
            ('cancel', "Cancelled"),
        ],
        string="Status", default='draft', required=True,
        tracking=True, copy=False)
    user_id = fields.Many2one(
        comodel_name='res.users', string="Counted By",
        default=lambda self: self.env.user, tracking=True)
    line_ids = fields.One2many(
        comodel_name='van.sales.reconciliation.line',
        inverse_name='reconciliation_id', string="Lines")
    line_count = fields.Integer(compute='_compute_line_counts', string="Lines")
    variance_count = fields.Integer(
        compute='_compute_line_counts', string="Variances")
    note = fields.Text(string="Notes")

    return_picking_id = fields.Many2one(
        comodel_name='stock.picking', string="Return Transfer",
        readonly=True, copy=False, check_company=True,
        help="Transfer sending the counted stock back to the warehouse, "
             "raised from this reconciliation.")
    return_qty_total = fields.Float(
        string="To Return", compute='_compute_return_qty_total',
        digits='Product Unit')
    can_create_return = fields.Boolean(compute='_compute_can_create_return')

    _van_date_uniq = models.Constraint(
        'UNIQUE(name, company_id)',
        "A reconciliation with this reference already exists.",
    )

    # --------------------------------------------------------------------
    # Defaults / compute
    # --------------------------------------------------------------------
    @api.model
    def _default_date_from(self):
        """Midnight today in the user's timezone, stored as naive UTC."""
        now_local = fields.Datetime.context_timestamp(
            self, fields.Datetime.now())
        start_local = now_local.replace(
            hour=0, minute=0, second=0, microsecond=0)
        return start_local.astimezone(pytz.utc).replace(tzinfo=None)

    @api.depends('line_ids.difference_qty')
    def _compute_line_counts(self):
        for record in self:
            lines = record.line_ids
            record.line_count = len(lines)
            record.variance_count = len(lines.filtered(
                lambda l: not l.product_uom_id.is_zero(l.difference_qty)
                if l.product_uom_id else bool(l.difference_qty)))

    # --------------------------------------------------------------------
    # Constraints
    # --------------------------------------------------------------------
    @api.depends('line_ids.return_qty')
    def _compute_return_qty_total(self):
        for record in self:
            record.return_qty_total = sum(record.line_ids.mapped('return_qty'))

    @api.depends('state', 'return_picking_id', 'return_picking_id.state')
    def _compute_can_create_return(self):
        """Returning is only meaningful once the count has been applied.

        Before that the van's system quantity is still the pre-count figure, so
        a return raised from it would move quantities nobody has verified.
        """
        for record in self:
            has_live_return = bool(
                record.return_picking_id
                and record.return_picking_id.state != 'cancel')
            record.can_create_return = (
                record.state == 'done' and not has_live_return)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for record in self:
            if record.date_from and record.date_to \
                    and record.date_to < record.date_from:
                raise UserError(_(
                    "The end of the period cannot be before its start on %s.",
                    record.display_name))

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
    # Line generation
    # --------------------------------------------------------------------
    def _van_location_ids(self):
        """The van location and everything under it."""
        self.ensure_one()
        return self.env['stock.location'].search(
            [('id', 'child_of', self.van_location_id.id)]).ids

    def _collect_movement_data(self):
        """Per-product movement and stock figures, in the product's own UoM.

        ``stock.move.quantity`` is stored in the *move's* unit of measure, not
        the product's, so every figure is converted - the same thing core does
        in ``product.product._compute_quantities_dict``. Getting this wrong is
        invisible until someone sells in cartons and counts in pieces.

        sudo: reconciling a van has to see every movement in and out of its
        location, including transfers raised by warehouse staff the salesman
        cannot otherwise read. Scoped strictly to this van's locations.
        """
        self.ensure_one()
        location_ids = self._van_location_ids()
        data = defaultdict(lambda: dict.fromkeys(QTY_FIELDS, 0.0))
        if not location_ids:
            return data

        Move = self.env['stock.move'].sudo()
        base = [
            ('state', '=', 'done'),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ]
        # 'in'/'not in' on resolved ids rather than 'child_of' on both legs:
        # unambiguous, and it excludes shuffles inside the van itself.
        in_domain = base + [
            ('location_dest_id', 'in', location_ids),
            ('location_id', 'not in', location_ids),
        ]
        out_domain = base + [
            ('location_id', 'in', location_ids),
            ('location_dest_id', 'not in', location_ids),
        ]

        for product, uom, counterpart, quantity in Move._read_group(
                in_domain, ['product_id', 'product_uom', 'location_id'],
                ['quantity:sum']):
            converted = uom._compute_quantity(
                quantity, product.uom_id, round=False)
            bucket = IN_BUCKETS.get(counterpart.usage, 'in_other_qty')
            data[product.id][bucket] += converted

        for product, uom, counterpart, quantity in Move._read_group(
                out_domain, ['product_id', 'product_uom', 'location_dest_id'],
                ['quantity:sum']):
            converted = uom._compute_quantity(
                quantity, product.uom_id, round=False)
            bucket = OUT_BUCKETS.get(counterpart.usage, 'out_other_qty')
            data[product.id][bucket] += converted

        # stock.quant.quantity is already in the product's UoM
        for product, quantity in self.env['stock.quant'].sudo()._read_group(
                [('location_id', 'in', location_ids)],
                ['product_id'], ['quantity:sum']):
            data[product.id]['expected_qty'] += quantity

        return data

    def action_generate_lines(self):
        """Build or refresh the lines. Counted quantities are preserved."""
        for record in self:
            if record.state != 'draft':
                raise UserError(_(
                    "%(name)s is %(state)s, so its lines cannot be "
                    "regenerated.",
                    name=record.display_name, state=record.state))
            record._generate_lines()
        return True

    def _generate_lines(self):
        self.ensure_one()
        data = self._collect_movement_data()
        Line = self.env['van.sales.reconciliation.line']
        existing = {line.product_id.id: line for line in self.line_ids}

        for product_id, figures in data.items():
            total_in = figures['in_load_qty'] + figures['in_other_qty']
            total_out = (figures['out_sale_qty'] + figures['out_return_qty']
                         + figures['out_adjust_qty'] + figures['out_other_qty'])
            values = dict(figures)
            # Opening is derived, so opening + in - out == expected exactly.
            values['opening_qty'] = figures['expected_qty'] - total_in + total_out
            line = existing.get(product_id)
            if line:
                line.write(values)
            else:
                # Counted starts at the system quantity on purpose: an
                # untouched line then has a zero difference and adjusts
                # nothing. Defaulting it to zero would silently write off
                # every product the counter did not get to.
                values.update({
                    'reconciliation_id': self.id,
                    'product_id': product_id,
                    'counted_qty': figures['expected_qty'],
                })
                Line.create(values)

    # --------------------------------------------------------------------
    # Applying
    # --------------------------------------------------------------------
    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group(
                'van_sales_base.group_van_sales_manager'):
            raise AccessError(_(
                "Only a Van Sales Administrator can apply a stock "
                "reconciliation."))
        if self.state != 'draft':
            raise UserError(_(
                "%(name)s is already %(state)s.",
                name=self.display_name, state=self.state))
        if not self.line_ids:
            raise UserError(_(
                "%s has no lines. Generate them first.", self.display_name))

        adjusted = self._apply_differences()
        self.state = 'done'
        self.message_post(body=_(
            "Reconciliation applied. %(adjusted)s product(s) adjusted out of "
            "%(total)s counted.",
            adjusted=adjusted, total=len(self.line_ids)))
        return True

    def _apply_differences(self):
        """Write the counted quantities into stock as an inventory adjustment.

        Uses ``_apply_inventory()`` rather than ``action_apply_inventory()``.
        The public method silently does nothing and returns a wizard action
        when a quant is ``is_outdated`` - that is, when something moved between
        counting and applying - which for a programmatic caller means the
        adjustment quietly never happened. Recomputing the difference against
        the live quantity first is the "keep counted quantity" resolution the
        conflict wizard itself offers.

        sudo: applying an adjustment needs Inventory User, which a Van Sales
        Administrator does not necessarily hold. The caller is gated on the van
        sales manager group above, and every write is confined to this van's
        location.
        """
        self.ensure_one()
        Quant = self.env['stock.quant'].sudo().with_context(
            inventory_mode=True)
        location = self.van_location_id
        adjusted = 0
        for line in self.line_ids:
            uom = line.product_id.uom_id
            if uom.compare(line.counted_qty, line.expected_qty) == 0:
                continue
            quant = Quant.create({
                'product_id': line.product_id.id,
                'location_id': location.id,
                'inventory_quantity': line.counted_qty,
            })
            # Live quantity may have moved on since the count.
            quant.inventory_diff_quantity = line.counted_qty - quant.quantity
            quant._apply_inventory()
            adjusted += 1
        return adjusted

    # --------------------------------------------------------------------
    # Returning the counted stock to the warehouse
    # --------------------------------------------------------------------
    def action_set_return_all(self):
        """Send everything counted back - the van empties overnight."""
        self.ensure_one()
        if not self.can_create_return:
            raise UserError(_(
                "The counted quantities have to be applied before they can be "
                "returned, and %s has no return raised against it yet.",
                self.display_name))
        for line in self.line_ids:
            line.return_qty = line.counted_qty
        return True

    def action_clear_return(self):
        """Keep everything on the van."""
        self.ensure_one()
        self.line_ids.write({'return_qty': 0.0})
        return True

    def action_create_return_picking(self):
        """Raise the van return transfer from the counted quantities.

        Deliberately a separate step from Apply rather than part of it.
        Correcting the stock figure and physically sending goods back to the
        warehouse are two different decisions: plenty of operations leave stock
        on the van overnight, and fusing the two would empty it for them.

        The transfer is left for the warehouse to validate. Creating a
        validated transfer from a button would move stock before anyone has
        actually received it back.
        """
        self.ensure_one()
        if not self.env.user.has_group(
                'van_sales_base.group_van_sales_manager'):
            raise AccessError(_(
                "Only a Van Sales Administrator can raise a van return."))
        if self.state != 'done':
            raise UserError(_(
                "Apply the count before returning stock. %(name)s is "
                "%(state)s.", name=self.display_name, state=self.state))
        if self.return_picking_id and self.return_picking_id.state != 'cancel':
            raise UserError(_(
                "%(name)s already has the return transfer %(picking)s. Cancel "
                "it first if you need to raise another.",
                name=self.display_name,
                picking=self.return_picking_id.display_name))

        lines = self.line_ids.filtered(
            lambda l: l.product_id.uom_id.compare(l.return_qty, 0.0) > 0)
        if not lines:
            raise UserError(_(
                "No quantity is marked for return. Use Return All Counted "
                "Stock, or type quantities in the Return column."))

        van = self.van_id
        warehouse, picking_type = van._van_sales_internal_picking_type()
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': self.van_location_id.id,
            'location_dest_id': warehouse.lot_stock_id.id,
            'origin': self.name,
            'company_id': self.company_id.id,
            'van_reconciliation_id': self.id,
            'move_ids': [(0, 0, {
                'name': line.product_id.display_name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.return_qty,
                'product_uom': line.product_id.uom_id.id,
                'location_id': self.van_location_id.id,
                'location_dest_id': warehouse.lot_stock_id.id,
                'company_id': self.company_id.id,
            }) for line in lines],
        })
        picking.action_confirm()
        picking.action_assign()
        self.return_picking_id = picking
        self.message_post(body=_(
            "Return transfer %(picking)s raised for %(count)s product(s). It "
            "still has to be validated by the warehouse.",
            picking=picking.display_name, count=len(lines)))
        return self.action_view_return_picking()

    def action_view_return_picking(self):
        self.ensure_one()
        if not self.return_picking_id:
            raise UserError(_(
                "%s has no return transfer.", self.display_name))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Van Return"),
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': self.return_picking_id.id,
        }

    # --------------------------------------------------------------------
    # State actions
    # --------------------------------------------------------------------
    def action_cancel(self):
        blocked = self.filtered(lambda r: r.state == 'done')
        if blocked:
            raise UserError(_(
                "An applied reconciliation cannot be cancelled. Correct it "
                "with a new inventory adjustment instead: %s",
                ", ".join(blocked.mapped('display_name'))))
        self.write({'state': 'cancel'})

    def action_draft(self):
        for record in self:
            if record.state != 'cancel':
                raise UserError(_(
                    "Only a cancelled reconciliation can be reset to draft. "
                    "%(name)s is %(state)s.",
                    name=record.display_name, state=record.state))
        self.write({'state': 'draft'})

    def action_view_moves(self):
        """Every movement in or out of the van in the period."""
        self.ensure_one()
        location_ids = self._van_location_ids()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Van Movements"),
            'res_model': 'stock.move.line',
            'view_mode': 'list,form',
            'domain': [
                ('state', '=', 'done'),
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
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
    state = fields.Selection(
        related='reconciliation_id.state', store=True, string="Status")

    opening_qty = fields.Float(
        string="Opening", digits='Product Unit', readonly=True)
    in_load_qty = fields.Float(
        string="Loaded", digits='Product Unit', readonly=True,
        help="Received from the warehouse or another internal location.")
    in_other_qty = fields.Float(
        string="Other In", digits='Product Unit', readonly=True,
        help="Customer returns and inventory gains.")
    out_sale_qty = fields.Float(
        string="Sold / Delivered", digits='Product Unit', readonly=True,
        help="Moved to a customer location. Free-of-charge goods are included "
             "here: at stock level they are indistinguishable from a sale.")
    out_return_qty = fields.Float(
        string="Returned", digits='Product Unit', readonly=True,
        help="Sent back to the warehouse or another internal location.")
    out_adjust_qty = fields.Float(
        string="Written Off", digits='Product Unit', readonly=True,
        help="Moved to an inventory-loss location by an earlier adjustment.")
    out_other_qty = fields.Float(
        string="Other Out", digits='Product Unit', readonly=True)
    expected_qty = fields.Float(
        string="System", digits='Product Unit', readonly=True,
        help="What Odoo believes is on the van right now.")
    counted_qty = fields.Float(
        string="Counted", digits='Product Unit',
        help="Starts at the system quantity, so a line you do not touch "
             "adjusts nothing. Change only what you actually counted "
             "differently.")
    difference_qty = fields.Float(
        string="Difference", digits='Product Unit',
        compute='_compute_difference_qty', store=True,
        help="Counted minus system. Negative means stock is missing.")

    return_qty = fields.Float(
        string="Return", digits='Product Unit', copy=False,
        help="How much of the counted stock goes back to the warehouse. "
             "Zero means it stays on the van overnight.")
    return_editable = fields.Boolean(compute='_compute_return_editable')

    _product_reconciliation_uniq = models.Constraint(
        'UNIQUE(reconciliation_id, product_id)',
        "This product is already on this reconciliation.",
    )

    @api.depends('counted_qty', 'expected_qty')
    def _compute_difference_qty(self):
        for line in self:
            line.difference_qty = line.counted_qty - line.expected_qty

    @api.depends('reconciliation_id.can_create_return')
    def _compute_return_editable(self):
        for line in self:
            line.return_editable = line.reconciliation_id.can_create_return

    @api.constrains('return_qty', 'counted_qty')
    def _check_return_qty(self):
        for line in self:
            uom = line.product_id.uom_id
            if uom.compare(line.return_qty, 0.0) < 0:
                raise UserError(_(
                    "The return quantity of %s cannot be negative.",
                    line.product_id.display_name))
            if uom.compare(line.return_qty, line.counted_qty) > 0:
                raise UserError(_(
                    "You cannot return %(return)s of %(product)s: only "
                    "%(counted)s were counted on the van.",
                    **{'return': line.return_qty,
                       'product': line.product_id.display_name,
                       'counted': line.counted_qty}))
