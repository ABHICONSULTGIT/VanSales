# Van Sales - Sale (`van_sales_sale`)

Third module of the Van Sales suite. **Odoo 19 Enterprise**, version `19.0.1.0.0`.
Depends on `van_sales_stock`, `sale_management`, `sale_stock`, `account`.

**Read the "Not built, and why" section before testing.** This module is
deliberately partial: roughly half of the order-to-cash requirement depends on
decisions the client has not made, and guessing them would have been worse than
waiting.

## What it does

### Delivery leaves the van, not the warehouse

This is the technical crux of the whole suite, and it needed care.

A sale order's delivery takes its source location from the `stock.rule` that
procurement matches — read off `rule.location_src_id` and **nowhere else**.
There is no values key in `stock`, `sale` or `sale_stock` that lets a caller
override it; verified by reading `stock.rule._get_stock_move_values`.

So each van gets its **own delivery route**, whose single pull rule sources from
that van's stock location. `sale.order.line._prepare_procurement_values` adds
that route to the procurement values, which is the officially supported lever —
`stock.rule._get_rule` gives those routes top priority. Odoo's own procurement
does everything else, so quantity delivered, invoice status, backorders and
returns behave exactly as standard.

Cost: one `stock.route` and one `stock.rule` per van, plus **one shared
operation type per warehouse** — not one per van, because the source comes from
the rule rather than the operation type. Routes are auto-provisioned when a van
is created, and a `post_init_hook` back-fills vans that already exist.

Rejected alternatives, for the record: a warehouse per van (eight operation
types and eight sequences each — 800 at full fleet), and a POS-style
hand-built picking (needs `sale_line_id` set manually or `qty_delivered` stays
zero, and you inherit reservation, backorder and return behaviour).

### Sell from a visit

**Sell Here** on a customer stop raises an order with the customer, van, route,
visit and van delivery route already set, and stamps when the salesman actually
took it — which is not when the server received it.

### Over-sell enforcement

The policy configured in *Van Sales - Stock* is applied **here**, at order
confirmation, because this is where a line is actually sold. Quantities are
summed **per product across lines** — three lines of six each must fail against
a van carrying ten, even though no single line does — and converted into the
product's own unit first.

`block` refuses the confirmation. `warn` confirms and records it on the chatter:
a backend action cannot raise a non-blocking dialog, so the warning is put
somewhere it stays rather than flashing past. The mobile app will show it as a
prompt.

### Credit policy

Odoo **only ever warns** about a credit limit — `_build_credit_warning_message`
returns a string that views render as a banner, and there is no hard block
anywhere in the product. A company setting (Accounting → Settings, next to
Sales Credit Limit) turns that into a block when the business wants one.

The evaluation itself reuses Odoo's own, so it stays consistent with the banner
the accountant sees elsewhere.

### Cash collection

One receipt, several invoices, an explicit amount against each.

This needed its own document. `reconcile()` on a payment and a set of invoices
allocates **first-in-first-out by due date** and cannot be told to put 300 on
one invoice and 200 on another — which is exactly what a salesman does. The
only way to control the split is **one `account.payment` per invoice**, each
reconciled to that invoice alone. The collection is what the customer sees; the
payments are the accounting behind it.

Allocated amounts start at **zero** on every line. Defaulting them to the full
residual would post money nobody received — the same reasoning as Counted
defaulting to the system quantity in the reconciliation.

Guarded against: allocating more than is owed, an unposted invoice, another
customer's invoice, a cross-currency collection (refused rather than silently
wrong), a payment that produced no journal entry, and an invoice whose
receivable account no longer matches the payment's.

## Not built, and why

Each of these is blocked on a decision the client has not made. They are all
**additive** — new fields and new documents, no rework of what is here.

| Held | Blocked on |
|---|---|
| **Free-of-charge goods** | Is FOC the salesman's discretion or a promotion rule? What is the tax treatment? Which expense account absorbs the cost? Any cap per visit or customer? |
| **Returns and credit notes** | Do returned goods re-enter saleable van stock or a quarantine location? Does a credit note need approval? Are returns allowed without a reference invoice? Any time limit? |
| **End-of-day cash hand-in** | Journal structure per van, whether a cash-in-transit account is used, who counts and confirms, what happens to a shortfall. |
| **Walk-up buyer identity on a location route** | Odoo will not post a customer invoice without a partner. One generic walk-in contact? One per van? Capture a name each time? Until this is answered the salesman picks a partner, rather than this module filing every walk-up sale against a guessed account. |
| **Sync-failure semantics** | What happens to an order that fails a server-side rule *after* the goods were handed over. Belongs to `van_sales_sync` in any case. |

Also outstanding and more urgent than any of the above: **country, tax regime
and whether e-invoicing is mandatory**. On a fresh database the localisation
package has to be chosen before the chart of accounts exists, and a clearance
regime would change whether an invoice can be raised offline at all.

## Security

Roles imply the standard Odoo groups rather than re-granting ACLs that would
then have to be kept in step:

| Van Sales role | Also gets |
|---|---|
| User | Sales: User — Own Documents Only (which brings sale's own record rule, so a salesman sees only their own orders, free) |
| Supervisor | Sales: User — All Documents |
| Administrator | Billing |

Posting a collection runs elevated, because a salesman does not hold Billing
rights. Every value is fixed by the document — inbound, this customer, this
journal, an amount already validated against the invoice's own residual — and
the acting user is recorded on the collection.

**Known scoping gap, stated rather than half-fixed:** van sales users get read
on `account.move` without a restrictive record rule, so a salesman can read
invoices beyond their own van in the backend. Adding a partial restriction here
would make the security story inconsistent rather than tighter — `stock` already
exposes all quants and move lines to every internal user. The real data boundary
for the mobile client is the sync API in `van_sales_sync`.

## Quick test path

1. Install. Check a van's form: **Van Sales** tab now shows a **Van Delivery
   Route**.
2. Open a visit at a customer stop, check in, press **Sell Here**.
3. Add a product the van is carrying, confirm. Check the delivery: its **source
   location is the van**, not `WH/Stock`.
4. Validate the delivery, create the invoice, post it.
5. Add a line for more than the van carries, on a product whose category policy
   is **Block** — confirmation is refused and says what is short.
6. Set the company credit policy to **Block**, give the customer a small limit,
   and try to confirm past it.
7. **Collect Cash** on the visit → Load Open Invoices → allocate part of one
   invoice → Post. Check the invoice is `partial` and the payment is linked.

## A note on `van_sales_stock`

Installing this module also fixes a latent bug found while building it: a
delivery **out of** a van location was classifying as a **Van Return**, because
the classification only looked at whether each end was a van. It now checks the
destination's usage, so a sale is a *Van Delivery* and only stock going back to
an internal location is a return. `van_sales_stock` is bumped to `19.0.1.2.0`.
If you ran the stock scenario, its simulated sales will reclassify on upgrade.
