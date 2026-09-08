# Part of the Van Sales project.

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class VanSalesVisit(models.Model):
    _inherit = 'van.sales.visit'

    sale_order_ids = fields.One2many(
        comodel_name='sale.order', inverse_name='van_visit_id',
        string="Orders")
    sale_order_count = fields.Integer(
        string="Orders", compute='_compute_sale_counts')
    invoice_count = fields.Integer(
        string="Invoices", compute='_compute_sale_counts')
    collection_count = fields.Integer(
        string="Collections", compute='_compute_sale_counts')

    def _compute_sale_counts(self):
        orders, invoices, collections = {}, {}, {}
        if self.ids:
            for visit, count in self.env['sale.order']._read_group(
                    [('van_visit_id', 'in', self.ids)],
                    ['van_visit_id'], ['__count']):
                orders[visit.id] = count
            for visit, count in self.env['account.move']._read_group(
                    [('van_visit_id', 'in', self.ids),
                     ('move_type', 'in', ('out_invoice', 'out_refund'))],
                    ['van_visit_id'], ['__count']):
                invoices[visit.id] = count
            for visit, count in self.env['van.sales.collection']._read_group(
                    [('visit_id', 'in', self.ids)], ['visit_id'], ['__count']):
                collections[visit.id] = count
        for visit in self:
            visit.sale_order_count = orders.get(visit.id, 0)
            visit.invoice_count = invoices.get(visit.id, 0)
            visit.collection_count = collections.get(visit.id, 0)

    # --------------------------------------------------------------------
    # Actions
    # --------------------------------------------------------------------
    def _van_sales_selling_partner(self):
        """The customer this stop sells to.

        A customer stop sells to its shop. A location stop sells to whoever
        walks up, and who that is on the paperwork is an open question with the
        client - Odoo will not post a customer invoice without a partner. Until
        it is answered the salesman picks one, rather than this module guessing
        and quietly filing every walk-up sale against the wrong account.
        """
        self.ensure_one()
        if self.stop_type == 'customer':
            return self.partner_id
        return self.env['res.partner']

    def action_van_sales_new_order(self):
        self.ensure_one()
        if self.state not in ('checked_in', 'done'):
            raise UserError(_(
                "Check in at %s before selling there.", self.display_name))
        van = self.van_id
        if not van or not van.van_location_id:
            raise UserError(_(
                "This visit has no van with a stock location behind it."))
        context = {
            'default_van_id': van.id,
            'default_van_route_id': self.route_id.id,
            'default_van_visit_id': self.id,
            'default_van_captured_datetime': fields.Datetime.now(),
        }
        partner = self._van_sales_selling_partner()
        if partner:
            context['default_partner_id'] = partner.id
        return {
            'type': 'ir.actions.act_window',
            'name': _("New Order"),
            'res_model': 'sale.order',
            'view_mode': 'form',
            'context': context,
        }

    def action_van_sales_view_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Orders"),
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('van_visit_id', '=', self.id)],
            'context': {'default_van_visit_id': self.id},
        }

    def action_van_sales_view_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Invoices"),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('van_visit_id', '=', self.id),
                       ('move_type', 'in', ('out_invoice', 'out_refund'))],
        }

    def action_van_sales_new_collection(self):
        self.ensure_one()
        partner = self._van_sales_selling_partner()
        context = {
            'default_van_id': self.van_id.id,
            'default_visit_id': self.id,
        }
        if partner:
            context['default_partner_id'] = partner.id
        return {
            'type': 'ir.actions.act_window',
            'name': _("Cash Collection"),
            'res_model': 'van.sales.collection',
            'view_mode': 'form',
            'context': context,
        }
