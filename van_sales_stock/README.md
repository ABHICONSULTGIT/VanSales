# Van Sales - Stock (`van_sales_stock`)

Second module of the Van Sales suite. **Odoo 19 Enterprise**, version `19.0.1.1.0`.

Delivers items C-07 … C-11 of the development plan. Depends on
`van_sales_base` and `stock`.

## Installation

The module sits in the addons directory you already added. Restart, update the
apps list, install **Van Sales - Stock**.

Installing runs a `post_init_hook`. It is not optional housekeeping — see
*Storage Locations* below.

## What it provides

### Van loads and returns

A van load is an **ordinary Odoo internal transfer** from the warehouse into a
van's stock location. There is deliberately no parallel "van load" document: a
wrapper model would duplicate state and lose standard valuation, traceability
and reporting.

Instead every transfer is classified from its own source and destination:

| Source | Destination | `van_operation` |
|---|---|---|
| warehouse | van location | Van Load |
| van location | warehouse | Van Return |
| van A | van B | Van to Van |

So a transfer the office raises the normal way in Inventory is picked up
automatically — there is no new process for warehouse staff to learn. The
**Load Van** and **Return Stock** buttons on the vehicle form just pre-fill the
locations.

Resolution walks `stock.location.parent_path`, so a sub-location *inside* a van
still resolves to that van, and it costs one query no matter how many transfers
are being computed.

### Discrepancy capture

Short or over receipt is already in the data: Odoo records demanded quantity
(`product_uom_qty`) and done quantity (`quantity`) separately. `van_discrepancy_qty`
is the difference, converted into the product's own unit of measure, computed
only once the transfer is **done** — before that the gap is just work in
progress. An alert on the form asks for the reason when there is one.

The reason is free text. A reason-code list is a small addition once the client
supplies the codes; inventing codes would have been a guess.

### Over-sell policy

**Odoo 19 has no negative-stock setting of any kind.** There is no
`allow_negative_stock` field on the product, the category, the location or the
company — verified by grep across all 1452 modules. Negative quants are
permitted; only negative *move-line* quantities are blocked. So the requirement
"prevent (or warn on) selling beyond van stock, configurable per product" has
nothing behind it in standard Odoo and is implemented here:

- `product.category.van_sale_stock_policy` — Allow / Warn / Block, default **Warn**
- `product.template.van_sale_stock_policy` — the same, plus *Use Category Policy* (default)
- `fleet.vehicle._van_sales_check_quantity(product, qty, uom)` — the service that
  returns the verdict, converting the quantity into the product's UoM first

This module supplies the policy and the check. **The enforcement point is in
`van_sales_sale`**, because that is where a line is actually sold. Nothing
enforces it yet.

### End-of-day reconciliation

`van.sales.reconciliation` counts what is physically on a van against what Odoo
believes, with the movements that explain the difference:

```
Opening + Loaded + Other In − Sold − Returned − Written Off − Other Out = System
System vs Counted = Difference
```

Movements are classified by the **usage of the location on the other side** of
the move: `customer` → Sold, `internal`/`transit` → Loaded or Returned,
`inventory` → Written Off. That is derived from what actually moved, so it is
decision-free.

Two consequences worth understanding:

**It is computed from `stock.move`, not from sales documents.** That means it is
correct today with no sales module installed, and once `van_sales_sale` exists
its deliveries appear in the Sold column automatically with nothing to wire up.

**Free-of-charge goods are not split out.** At stock level an FOC line and a
sold line both move stock to a customer location and are indistinguishable. The
split needs the FOC flag, which lives in the sales module. Until then FOC is
counted inside *Sold*.

Applying posts a standard inventory adjustment through
`stock.quant` in inventory mode.

### Returning the counted stock

Once a reconciliation is **Applied**, the van's system stock equals what was
counted — so that is the moment the return transfer can be raised from it,
without re-typing twenty product lines the document already knows.

**Return All Counted Stock** fills the Return column from the counted
quantities; **Create Return Transfer** raises the van-to-warehouse transfer and
links it back. The warehouse validates it on receipt.

Three deliberate choices:

- **It is a separate step from Apply, not part of it.** Correcting the stock
  figure and physically sending goods back are two different decisions. Plenty
  of van operations leave stock on the van overnight, and fusing the two would
  empty it for them.
- **It is only available after Apply.** Before that the van's system quantity is
  still the pre-count figure, so a return raised from it would move quantities
  nobody has verified. Guarded on the server, not just in the view.
- **The Return column defaults to zero.** Nothing moves unless somebody asks for
  it, and you cannot return more than was counted. Same reasoning as Counted
  defaulting to the system quantity.

The manual path is untouched: **Return Stock** on the van form still raises a
return directly, for partial returns mid-day or any time no count is involved.

## Design decisions worth knowing

### Storage Locations is turned on at install

Van sales cannot work without `stock.group_stock_multi_locations`: every van
*is* a stock location. Worse, `stock.warehouse._get_picking_type_create_values`
creates each warehouse's internal operation type with
`'active': self.env.user.has_group('stock.group_stock_multi_locations')` — so
without the group there is **no operation type to raise a van load against**,
and `warehouse.int_type_id` returns an archived record that a plain search will
not even find.

The `post_init_hook` does exactly what ticking Storage Locations in Inventory
settings does: adds the group to `base.group_user` and reactivates the archived
internal operation types. Mirrors `stock/models/res_config_settings.py.set_values`.

### A Van Sales Administrator implies Inventory User

Loading a van, validating a transfer and applying an adjustment are all
Inventory User operations. The role implies `stock.group_stock_user` rather than
this module re-granting a pile of stock ACLs it would then have to keep in step
with Odoo.

### The `stock.picking` record rule, and why there are three of them

`stock` ships **no** group-level record rule on `stock.picking` — only a global
multi-company one. Odoo OR-s group rules and counts only rules for groups the
user actually holds. So adding a restrictive van rule on its own would have
**silently narrowed what every existing Inventory user can see**. Three rules
keep every combination correct:

| User holds | Rules that match | Sees |
|---|---|---|
| Inventory User only | C | everything — **unchanged** |
| Van Sales User | A | their own van's transfers |
| Van Sales Supervisor | A or B | every van transfer |
| Van Sales Administrator | A or B or C | everything |

This is the same trap as the Fleet one in `van_sales_base`, in a different
model. Worth checking in UAT (**FLT**-style cases).

### Applying uses `_apply_inventory()`, not `action_apply_inventory()`

The public method **silently does nothing and returns a wizard action** when a
quant is `is_outdated` — that is, when something moved between counting and
applying. For a programmatic caller that means the adjustment quietly never
happened. The private method has no such guard, and the difference is
recomputed against the live quantity first, which is the "keep counted quantity"
resolution the conflict wizard itself offers.

### Counted starts at the system quantity

A line the counter never touches then has a zero difference and adjusts
nothing. Defaulting Counted to zero would have **written off every product the
counter did not reach** — the single most dangerous defect this model could
have had.

A consequence: this is not a *blind* count. If the client wants counters not to
see the system figure, say so — it needs a different entry flow, not a
different default.

### Unit-of-measure safety

`stock.move.quantity` is stored in the **move's** unit of measure, not the
product's. Every figure is converted with `uom._compute_quantity(...)`, exactly
as core does in `product.product._compute_quantities_dict`. Getting this wrong
stays invisible until someone sells in cartons and counts in pieces — which is
open decision D-17.

## Deliberately absent

- **Lot / expiry level reconciliation.** Product level only. Whether lots are
  tracked at all is open decision D-04, and lot columns would be dead weight if
  the answer is no.
- **Where returned goods land** (saleable van stock vs quarantine) is open
  decision D-05. Returns currently go wherever the transfer says.
- **A reason-code list** for discrepancies — free text until the client supplies
  codes.
- **Automatic end-of-day reconciliation** on a schedule. Started by hand.
- **Enforcement** of the over-sell policy — belongs in `van_sales_sale`.
- **Restrictive rules on `stock.quant` / `stock.move`.** Note that `stock` itself
  already grants every internal user read on quants and full access on move
  lines, so a partial restriction here would be a security story that is
  inconsistent rather than tighter. The real data boundary for the mobile client
  is the sync API in `van_sales_sync`.

## Quick test path

1. Install. Check Inventory → Configuration shows **Locations** (proves the hook ran).
2. Van form → **Load Van** → add products → Mark as Todo → Check Availability → Validate.
3. The transfer shows **Van Operation = Van Load** and a Van stat button.
4. Validate with a done quantity below demand → the discrepancy alert appears
   and asks for a reason.
5. Van form → **Reconcile Stock** → lines appear with Loaded filled in and
   Counted pre-set to System.
6. Change one Counted figure → **Apply** → check the resulting inventory
   adjustment in Inventory → Reporting → Moves History.
7. Still on the applied reconciliation → **Return All Counted Stock** →
   **Create Return Transfer** → validate it as the warehouse. The van is now
   empty and the warehouse has the stock back.
8. Log in as a salesman: they see only their own van's transfers. Log in as a
   plain Inventory user: they still see everything.
