# Part of the Van Sales project.

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class VanSalesCollection(models.Model):
    """One receipt, several invoices, an explicit amount against each.

    Why this exists rather than Odoo's payment register: ``reconcile()`` on a
    payment and a set of invoices allocates **first-in-first-out by due date**
    and cannot be told to put 300 on one invoice and 200 on another. A salesman
    standing in a shop does exactly that, so the allocation has to be explicit.

    The mechanism is one ``account.payment`` per invoice, reconciled to that
    invoice alone - the only way to control the split exactly. The collection
    is the document the customer sees; the payments are the accounting behind
    it.
    """

    _name = 'van.sales.collection'
    _inherit = ['mail.thread']
    _description = "Van Sales Cash Collection"
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string="Reference", required=True, copy=False, readonly=True,
        default=lambda self: _("New"))
    company_id = fields.Many2one(
        comodel_name='res.company', string="Company", required=True,
        index=True, default=lambda self: self.env.company)
    partner_id = fields.Many2one(
        comodel_name='res.partner', string="Customer", required=True,
        index=True, check_company=True, ondelete='restrict', tracking=True)
    van_id = fields.Many2one(
        comodel_name='fleet.vehicle', string="Van",
        domain="[('is_sales_van', '=', True)]",
        check_company=True, index='btree_not_null', tracking=True)
    visit_id = fields.Many2one(
        comodel_name='van.sales.visit', string="Visit",
        check_company=True, index='btree_not_null')
    salesman_user_id = fields.Many2one(
        comodel_name='res.users', string="Salesman",
        related='van_id.salesman_user_id', store=True,
        index='btree_not_null')
    journal_id = fields.Many2one(
        comodel_name='account.journal', string="Journal", required=True,
        domain="[('type', 'in', ('cash', 'bank')), ('company_id', '=', company_id)]",
        check_company=True,
        default=lambda self: self._default_journal_id(), tracking=True)
    currency_id = fields.Many2one(
        comodel_name='res.currency', string="Currency",
        compute='_compute_currency_id', store=True, readonly=True)
    date = fields.Date(
        string="Date", required=True, default=fields.Date.context_today,
        tracking=True)
    line_ids = fields.One2many(
        comodel_name='van.sales.collection.line',
        inverse_name='collection_id', string="Allocation")
    amount_total = fields.Monetary(
        string="Total Collected", compute='_compute_amount_total',
        store=True, currency_field='currency_id')
    state = fields.Selection(
        selection=[
            ('draft', "Draft"),
            ('posted', "Posted"),
            ('cancel', "Cancelled"),
        ],
        string="Status", default='draft', required=True,
        tracking=True, copy=False)
    payment_ids = fields.One2many(
        comodel_name='account.payment', inverse_name='van_collection_id',
        string="Payments", readonly=True)
    payment_count = fields.Integer(compute='_compute_payment_count')
    memo = fields.Char(string="Memo")
    van_client_uuid = fields.Char(
        string="Client Reference", copy=False, index='btree_not_null')

    _van_client_uuid_uniq = models.Constraint(
        'UNIQUE(van_client_uuid)',
        "A collection with this client reference already exists.",
    )

    # --------------------------------------------------------------------
    # Defaults / compute
    # --------------------------------------------------------------------
    @api.model
    def _default_journal_id(self):
        van_id = self.env.context.get('default_van_id')
        if van_id:
            van = self.env['fleet.vehicle'].browse(van_id)
            if van.cash_journal_id:
                return van.cash_journal_id
        return self.env['account.journal'].search([
            ('type', '=', 'cash'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)

    @api.depends('journal_id', 'company_id')
    def _compute_currency_id(self):
        for record in self:
            record.currency_id = (
                record.journal_id.currency_id
                or record.company_id.currency_id
                or self.env.company.currency_id)

    @api.depends('line_ids.amount')
    def _compute_amount_total(self):
        for record in self:
            record.amount_total = sum(record.line_ids.mapped('amount'))

    @api.depends('payment_ids')
    def _compute_payment_count(self):
        for record in self:
            record.payment_count = len(record.payment_ids)

    @api.onchange('van_id')
    def _onchange_van_id(self):
        if self.van_id.cash_journal_id and self.state == 'draft':
            self.journal_id = self.van_id.cash_journal_id

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
                        'van.sales.collection') or _("New")
        return super().create(vals_list)

    def unlink(self):
        blocked = self.filtered(lambda c: c.state == 'posted')
        if blocked:
            raise UserError(_(
                "A posted collection cannot be deleted - its payments are "
                "already in the accounts: %s",
                ", ".join(blocked.mapped('display_name'))))
        return super().unlink()

    # --------------------------------------------------------------------
    # Building the allocation
    # --------------------------------------------------------------------
    def _open_invoice_domain(self):
        self.ensure_one()
        return [
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('company_id', '=', self.company_id.id),
            ('partner_id', 'child_of',
             self.partner_id.commercial_partner_id.id),
        ]

    def action_load_open_invoices(self):
        """Pull in the customer's unpaid invoices, oldest first.

        Amounts start at zero. The salesman types what was actually handed
        over - defaulting to the full residual would post money nobody
        received.
        """
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_(
                "%s is no longer draft.", self.display_name))
        if not self.partner_id:
            raise UserError(_("Choose the customer first."))
        invoices = self.env['account.move'].search(
            self._open_invoice_domain(), order='invoice_date_due, id')
        already = self.line_ids.mapped('move_id')
        values = [
            {'collection_id': self.id, 'move_id': invoice.id, 'amount': 0.0}
            for invoice in invoices if invoice not in already
        ]
        if not values and not self.line_ids:
            raise UserError(_(
                "%s has no unpaid invoices.", self.partner_id.display_name))
        if values:
            self.env['van.sales.collection.line'].create(values)
        return True

    def action_allocate_full(self):
        """Settle every listed invoice in full."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("%s is no longer draft.", self.display_name))
        for line in self.line_ids:
            line.amount = line.move_residual
        return True

    def action_clear_allocation(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("%s is no longer draft.", self.display_name))
        self.line_ids.write({'amount': 0.0})
        return True

    # --------------------------------------------------------------------
    # Posting
    # --------------------------------------------------------------------
    def _check_postable(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_(
                "%(name)s is already %(state)s.",
                name=self.display_name, state=self.state))
        lines = self.line_ids.filtered(
            lambda l: self.currency_id.compare_amounts(l.amount, 0.0) > 0)
        if not lines:
            raise UserError(_(
                "Nothing is allocated. Enter what the customer paid against "
                "each invoice, or use Allocate In Full."))
        for line in lines:
            invoice = line.move_id
            if invoice.state != 'posted':
                raise UserError(_(
                    "Invoice %s is not posted.", invoice.display_name))
            if invoice.currency_id != self.currency_id:
                raise UserError(_(
                    "Invoice %(invoice)s is in %(their)s but this collection "
                    "is in %(ours)s. Odoo cannot reconcile across currencies "
                    "here - collect it on a journal in %(their)s.",
                    invoice=invoice.display_name,
                    their=invoice.currency_id.name,
                    ours=self.currency_id.name))
            if invoice.commercial_partner_id != self.partner_id.commercial_partner_id:
                raise UserError(_(
                    "Invoice %(invoice)s belongs to %(other)s, not %(partner)s.",
                    invoice=invoice.display_name,
                    other=invoice.commercial_partner_id.display_name,
                    partner=self.partner_id.display_name))
            if self.currency_id.compare_amounts(
                    line.amount, invoice.amount_residual) > 0:
                raise UserError(_(
                    "You cannot allocate %(amount)s to %(invoice)s: only "
                    "%(residual)s is still owed on it.",
                    amount=line.amount,
                    invoice=invoice.display_name,
                    residual=invoice.amount_residual))
        return lines

    def _payment_method_line(self):
        self.ensure_one()
        method = self.journal_id.inbound_payment_method_line_ids.filtered(
            lambda l: l.code == 'manual')[:1]
        if not method:
            method = self.journal_id.inbound_payment_method_line_ids[:1]
        if not method:
            raise UserError(_(
                "Journal %s has no inbound payment method, so a customer "
                "payment cannot be recorded on it.",
                self.journal_id.display_name))
        return method

    def action_post(self):
        self.ensure_one()
        if not self.env.user.has_group(
                'van_sales_base.group_van_sales_user'):
            raise AccessError(_(
                "Only van sales users can post a collection."))
        lines = self._check_postable()
        method = self._payment_method_line()
        # sudo: posting a customer payment is a Billing operation, and a van
        # salesman does not hold Billing rights. Every value is fixed by this
        # document - inbound, this customer, this journal, an amount already
        # validated against the invoice's own residual - and the acting user is
        # recorded on the collection, so the audit trail survives.
        Payment = self.env['account.payment'].sudo()

        for line in lines:
            invoice = line.move_id
            payment = Payment.create({
                'payment_type': 'inbound',
                'partner_type': 'customer',
                'partner_id': self.partner_id.id,
                'amount': line.amount,
                'currency_id': self.currency_id.id,
                'journal_id': self.journal_id.id,
                'payment_method_line_id': method.id,
                'date': self.date,
                'company_id': self.company_id.id,
                'memo': self.memo or self.name,
                'van_id': self.van_id.id,
                'van_visit_id': self.visit_id.id,
                'van_collection_id': self.id,
            })
            payment.action_post()

            # Posting builds the journal entry lazily; without it there is
            # nothing to reconcile and the invoice would quietly stay unpaid.
            if not payment.move_id or payment.move_id.state != 'posted':
                raise UserError(_(
                    "The payment for %s did not produce a posted journal "
                    "entry. Check the journal's outstanding account.",
                    invoice.display_name))

            counterpart = payment._seek_for_lines()[1]
            if len(counterpart) != 1:
                raise UserError(_(
                    "The payment for %s did not produce a single receivable "
                    "line, so it cannot be matched to the invoice.",
                    invoice.display_name))
            invoice_lines = invoice.line_ids.filtered(
                lambda l, account=counterpart.account_id: (
                    l.account_id == account and not l.reconciled))
            if not invoice_lines:
                raise UserError(_(
                    "Invoice %(invoice)s does not use the receivable account "
                    "%(account)s that this payment posted to, so they cannot "
                    "be matched. The customer's receivable account has "
                    "probably changed since the invoice was raised.",
                    invoice=invoice.display_name,
                    account=counterpart.account_id.display_name))
            (counterpart + invoice_lines).sudo().reconcile()
            line.payment_id = payment

        self.state = 'posted'
        self.message_post(body=_(
            "Collected %(amount)s across %(count)s invoice(s).",
            amount=self.amount_total, count=len(lines)))
        return True

    def action_cancel(self):
        blocked = self.filtered(lambda c: c.state == 'posted')
        if blocked:
            raise UserError(_(
                "A posted collection cannot be cancelled here - its payments "
                "are in the accounts. Reverse the payments from Accounting "
                "instead: %s",
                ", ".join(blocked.mapped('display_name'))))
        self.write({'state': 'cancel'})

    def action_draft(self):
        for record in self:
            if record.state != 'cancel':
                raise UserError(_(
                    "Only a cancelled collection can be reset to draft."))
        self.write({'state': 'draft'})

    def action_view_payments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Payments"),
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'domain': [('van_collection_id', '=', self.id)],
        }


class VanSalesCollectionLine(models.Model):
    _name = 'van.sales.collection.line'
    _description = "Van Sales Cash Collection Line"
    _order = 'collection_id, id'
    _check_company_auto = True

    collection_id = fields.Many2one(
        comodel_name='van.sales.collection', string="Collection",
        required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        comodel_name='res.company', related='collection_id.company_id',
        store=True, index=True)
    currency_id = fields.Many2one(
        comodel_name='res.currency', related='collection_id.currency_id',
        store=True)
    state = fields.Selection(
        related='collection_id.state', store=True, string="Status")
    move_id = fields.Many2one(
        comodel_name='account.move', string="Invoice", required=True,
        index=True, check_company=True, ondelete='restrict',
        domain="[('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),"
               " ('payment_state', 'in', ('not_paid', 'partial'))]")
    move_date = fields.Date(related='move_id.invoice_date', string="Date")
    move_date_due = fields.Date(
        related='move_id.invoice_date_due', string="Due")
    move_total = fields.Monetary(
        related='move_id.amount_total', string="Invoice Total",
        currency_field='currency_id')
    move_residual = fields.Monetary(
        related='move_id.amount_residual', string="Owed",
        currency_field='currency_id')
    amount = fields.Monetary(
        string="Allocated", currency_field='currency_id',
        help="How much of the money collected settles this invoice. Starts at "
             "zero on purpose - type what the customer actually paid.")
    payment_id = fields.Many2one(
        comodel_name='account.payment', string="Payment",
        readonly=True, copy=False, index='btree_not_null')

    _move_collection_uniq = models.Constraint(
        'UNIQUE(collection_id, move_id)',
        "This invoice is already on this collection.",
    )

    @api.constrains('amount')
    def _check_amount(self):
        for line in self:
            if line.currency_id.compare_amounts(line.amount, 0.0) < 0:
                raise UserError(_(
                    "A negative amount cannot be allocated to %s.",
                    line.move_id.display_name))
