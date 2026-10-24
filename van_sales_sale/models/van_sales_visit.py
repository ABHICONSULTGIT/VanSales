# Part of the Van Sales project.

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class VanSalesVisit(models.Model):
    _inherit = 'van.sales.visit'

    sale_order_ids = fields.One2many(
        comodel_name='sale.order', inverse_name='van_visit_id',
        string="Orders")
    sale_order_id = fields.Many2one(
        comodel_name='sale.order', string="Sale Order",
        compute='_compute_sale_order_id', store=True, index='btree_not_null',
        help="The order taken at this stop. A cancelled order frees the stop "
             "for a new one.")

    @api.depends('sale_order_ids', 'sale_order_ids.state')
    def _compute_sale_order_id(self):
        for visit in self:
            active = visit.sale_order_ids.filtered(
                lambda order: order.state != 'cancel')
            visit.sale_order_id = active.sorted('id')[:1]

    # --------------------------------------------------------------------
    # ORM
    # --------------------------------------------------------------------
    @api.ondelete(at_uninstall=False)
    def _unlink_except_has_orders(self):
        blocked = self.filtered('sale_order_ids')
        if blocked:
            raise UserError(_(
                "These visits have sale orders and cannot be removed: %s. "
                "Delete or move the orders first.",
                ", ".join(blocked.mapped('display_name'))))

    # --------------------------------------------------------------------
    # Actions
    # --------------------------------------------------------------------
    def action_van_sales_new_order(self):
        """Open a new order for this stop, everything already filled in.

        A location-only stop has no customer, so the salesman picks one: Odoo
        will not invoice a sale without a partner.
        """
        self.ensure_one()
        if self.sale_order_id:
            raise UserError(_(
                "%(visit)s already has the order %(order)s.",
                visit=self.display_name,
                order=self.sale_order_id.display_name))
        van = self.van_id
        if not van or not van.van_location_id:
            raise UserError(_(
                "This visit has no van with a stock location behind it."))
        context = {
            'default_user_id': self.salesman_user_id.id,
            'default_van_id': van.id,
            'default_van_route_id': self.plan_id.route_id.id,
            'default_van_visit_id': self.id,
            'default_van_captured_datetime': fields.Datetime.now(),
        }
        if self.partner_id:
            context['default_partner_id'] = self.partner_id.id
        return {
            'type': 'ir.actions.act_window',
            'name': _("New Order"),
            'res_model': 'sale.order',
            'view_mode': 'form',
            'context': context,
        }


class VanSalesVisitPlan(models.Model):
    _inherit = 'van.sales.visit.plan'

    @api.ondelete(at_uninstall=False)
    def _unlink_except_has_orders(self):
        blocked = self.filtered(lambda plan: plan.visit_ids.sale_order_ids)
        if blocked:
            raise UserError(_(
                "These visit plans have sale orders and cannot be deleted: %s.",
                ", ".join(blocked.mapped('display_name'))))
