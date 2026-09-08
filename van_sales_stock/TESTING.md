# Van Sales - Stock: Unit / UAT Test Guide

Module `van_sales_stock` `19.0.1.1.0` · Odoo 19 Enterprise

Written against the code. Expected messages are quoted verbatim from the
source — different wording on screen is itself a finding.

Prerequisite: `van_sales_base` installed and its own `TESTING.md` broadly
passing. This guide assumes the Gulf Fresh master data already exists.

## How to record results

**P** passed · **F** failed, say what you saw · **?** works but you disagree
with the design · **N/A** couldn't test, say why.

Reply with only the F and ? rows: ID plus one line each. Cases marked
**[critical]** must pass before this module is worth reviewing further.
**[dev]** needs the shell and can be skipped on a first pass.

---

## 0. Setup

### 0.1 Products — this module needs them, `van_sales_base` did not

Create five storable products. Leave the unit of measure as **Units** for now:
cartons vs pieces is still an open decision, and mixing them mid-test would
confuse the results rather than test them.

| Product | Type | Category |
|---|---|---|
| Water 500ml Pack | Goods, **Track Inventory** on | Beverages |
| Water 1.5L Pack | Goods, Track Inventory on | Beverages |
| Orange Juice 1L | Goods, Track Inventory on | Beverages |
| Laban 1L | Goods, Track Inventory on | Dairy |
| Potato Chips Box | Goods, Track Inventory on | Snacks |

Create the two product categories **Beverages** and **Dairy** as well — DAI-02
needs a category whose policy differs.

### 0.2 Opening warehouse stock

Inventory → Operations → Physical Inventory. Put 500 of each product into
`WH/Stock` and Apply. Without this there is nothing to load.

---

## 1. Install and the post-init hook — INST

The hook is not housekeeping. Without it there is no operation type to raise a
van load against.

| ID | Steps | Expected | Result |
|---|---|---|---|
| INST-01 **[critical]** | Install **Van Sales - Stock** | Installs with no error, no traceback in the log | |
| INST-02 **[critical]** | Settings → Inventory → Warehouse section | **Storage Locations** is now ticked. The hook turned it on. | |
| INST-03 **[critical]** | Inventory → Configuration → Operation Types | The warehouse's **Internal Transfers** type exists and is **not archived** | |
| INST-04 | Van Sales → Operations | Three new entries: **Van Loads**, **Van Returns**, **Reconciliations** | |
| INST-05 | Settings → Users → open `van.fatima` | Her roles now include **Inventory / User**, picked up from the Van Sales Administrator role | |
| INST-06 | Settings → Technical → Sequences | **Van Stock Reconciliation**, prefix `VREC/<year>/` | |
| INST-07 | Upgrade the module a second time (`-u van_sales_stock`) | Clean, nothing duplicated | |

---

## 2. Over-sell policy — POL

Odoo 19 has no negative-stock setting anywhere, so this is the only control.

| ID | Steps | Expected | Result |
|---|---|---|---|
| POL-01 | Inventory → Configuration → Product Categories → Beverages | **Van Over-Sell Policy** field, default **Warn** | |
| POL-02 | Set Beverages to **Block**, Dairy to **Allow** | Both save | |
| POL-03 **[critical]** | Open Water 500ml → Inventory tab → Van Sales group | **Van Over-Sell Policy** = *Use Category Policy*, and **Effective Policy** shows **Block** (from Beverages) | |
| POL-04 | Set Water 500ml's own policy to **Warn** | Effective Policy field disappears; the product now overrides the category | |
| POL-05 | Set it back to *Use Category Policy* | Effective Policy returns to **Block** | |
| POL-06 **[dev]** | Shell: `van._van_sales_check_quantity(product, 5)` where the van holds 2 | Returns `{'ok': False, 'policy': 'block', 'available': 2.0, 'shortage': 3.0}` | |
| POL-07 **[dev]** | Same with a quantity the van has | `{'ok': True, ...}` | |
| POL-08 | Sell more than the van has, from anywhere in the UI | **Nothing is enforced yet.** Enforcement lives in `van_sales_sale`. Report it only if you expected otherwise. | |

---

## 3. Van loads — LOAD

| ID | Steps | Expected | Result |
|---|---|---|---|
| LOAD-01 **[critical]** | Van `GF-1234` → **Van Sales** tab → **Load Van** | A new transfer opens with Source = `WH/Stock`, Destination = `WH/Vans/GF-1234`, Origin = "Load …" | |
| LOAD-02 **[critical]** | Add 100 Water 500ml, 50 Juice. Mark as Todo → Check Availability → Validate | Validates. Van Sales group shows **Van Operation = Van Load**, **Van = GF-1234**, **Salesman = Rashid Kamal** | |
| LOAD-03 | Van form → **Van Stock** stat button | Shows 100 and 50 in the van's location | |
| LOAD-04 | Van form → **Transfers** stat button | The load is listed | |
| LOAD-05 **[critical]** | Inventory → Operations → Internal Transfers → New. Set Destination to `WH/Vans/GF-5678` by hand. Add products, validate. | It is recognised as a **Van Load** with no extra step — the classification comes from the locations, so a transfer raised the normal way is picked up | |
| LOAD-06 | Van Sales → Operations → **Van Loads** | Both loads listed, grouped by van | |
| LOAD-07 | A transfer between two ordinary warehouse locations | **Van Operation stays empty**; the Van Sales group is hidden. Non-van transfers are untouched. | |
| LOAD-08 **[dev]** | Create a sub-location under `WH/Vans/GF-1234` (e.g. "Shelf A") and transfer into it | Still classified as a Van Load for GF-1234 — resolution walks the location parents | |
| LOAD-09 | Log in as `van.rashid`, open the load | He can see it (read only) | |

---

## 4. Van returns and van-to-van — RET

| ID | Steps | Expected | Result |
|---|---|---|---|
| RET-01 **[critical]** | Van `GF-1234` → **Return Stock** | New transfer, Source = the van location, Destination = `WH/Stock` | |
| RET-02 | Add 10 Water 500ml, validate | **Van Operation = Van Return**, Van = GF-1234 | |
| RET-03 | Van Sales → Operations → **Van Returns** | Listed | |
| RET-04 | Internal transfer from `WH/Vans/GF-1234` to `WH/Vans/GF-5678`, validate | **Van Operation = Van to Van**; *From Van* and *To Van* both filled; it appears under Van Returns | |
| RET-05 | On that van-to-van transfer, check the **Van** field | Shows the **destination** van (the receiving one) | |

---

## 5. Discrepancy capture — DISC

| ID | Steps | Expected | Result |
|---|---|---|---|
| DISC-01 **[critical]** | Load Van with demand 100 Water. On the Operations tab set the done quantity to **95**. Validate, choosing **No Backorder** if asked. | Transfer done. An orange alert appears: the quantity received differs by **-5**. | |
| DISC-02 | Additional Info tab → Van Sales group | **Discrepancy Reason** field is now visible. Enter `5 packs damaged in loading`. Saves. | |
| DISC-03 | Load with done **105** against demand 100 | Alert shows **+5** (over receipt) | |
| DISC-04 | A load where done exactly equals demand | **No alert**, and the reason field stays hidden | |
| DISC-05 **[critical]** | A load still in Ready state with done quantity below demand | **No alert.** Before validation the gap is just work in progress, not a discrepancy. | |
| DISC-06 | Van Loads list → enable the **Has Discrepancy** optional column; search filter **With Discrepancy** | Both work | |

---

## 6. Reconciliation — REC

The core of this module. Do section 5 of the scenario document first if you
want realistic numbers.

| ID | Steps | Expected | Result |
|---|---|---|---|
| REC-01 **[critical]** | Van `GF-1234` → **Reconcile Stock** | A reconciliation opens, reference `VREC/<year>/0001`, state Draft, From = midnight today, To = now, lines already generated | |
| REC-02 **[critical]** | Look at the columns | **Loaded** shows today's loads; **System** shows current van stock; **Counted** is **pre-filled equal to System**; **Difference** is 0 | |
| REC-03 **[critical]** | Press **Apply** without changing anything | Applies, state → Applied, and **no stock changes at all**. This is the safety property: an untouched line adjusts nothing. | |
| REC-04 **[critical]** | New reconciliation. Change one product's **Counted** from 95 to 90. Apply. | State → Applied. Inventory → Reporting → Moves History shows an adjustment of **-5** for that product out of the van location. | |
| REC-05 | Chatter on the applied reconciliation | Logs how many products were adjusted out of how many counted | |
| REC-06 | Set Counted **higher** than System and apply | A positive adjustment into the van location | |
| REC-07 **[critical]** | After simulating sales (scenario §5), generate a reconciliation | **Sold / Delivered** column is filled from the moves to the customer location. Nothing was wired to sales — it reads the stock ledger. | |
| REC-08 | After a van return, generate again | **Returned** column filled | |
| REC-09 | After a physical-inventory write-off on the van location, generate again | **Written Off** column filled | |
| REC-10 **[critical]** | Check the arithmetic on any line | `Opening + Loaded + Other In − Sold − Returned − Written Off − Other Out = System`, exactly | |
| REC-11 | **Movements** stat button | Opens every done move in or out of the van in the period | |
| REC-12 | Set From to tomorrow and To to today, save | Blocked: *"The end of the period cannot be before its start on …"* | |
| REC-13 | Narrow the window to the last hour and press **Generate Lines** | Figures shrink to that window; **Counted quantities you already typed are preserved** | |
| REC-14 | Press **Generate Lines** on an Applied reconciliation | *"… is applied, so its lines cannot be regenerated."* | |
| REC-15 | Press **Apply** on a reconciliation with no lines | *"… has no lines. Generate them first."* | |
| REC-16 | Press **Apply** twice | Second time: *"… is already done."* | |
| REC-17 | Delete an Applied reconciliation | *"An applied reconciliation cannot be deleted, because the inventory adjustments it made are already in the stock history…"* | |
| REC-18 | Cancel an Applied reconciliation | *"An applied reconciliation cannot be cancelled. Correct it with a new inventory adjustment instead…"* | |
| REC-19 | Cancel a Draft one, then **Reset to Draft** | Both work | |
| REC-20 | Reset an Applied one to draft | *"Only a cancelled reconciliation can be reset to draft…"* | |
| REC-21 | Try to add the same product twice to one reconciliation | *"This product is already on this reconciliation."* | |
| REC-22 | Reconcile a van with **no** stock location | *"Van … has no stock location, so its stock cannot be reconciled."* | |
| REC-23 **[critical]** | Open a reconciliation, and **before** applying it move stock out of that van in another tab. Then Apply. | The adjustment **still lands**, and the final quantity equals what you counted. (The public Odoo method silently does nothing here — this module deliberately avoids it.) | |
| REC-24 | Reconciliations list: filters *Draft*, *Applied*, *With Variance*; group by Van / Salesman / Status | All work | |
| REC-25 | Variance count on the form and list | Matches the number of lines whose Difference is non-zero | |

---

## 6b. Returning counted stock — RETC

New in `19.0.1.1.0`. Raises the van return from the reconciliation instead of
re-typing it.

| ID | Steps | Expected | Result |
|---|---|---|---|
| RETC-01 **[critical]** | On a **Draft** reconciliation, look for the return buttons | **Not shown.** Returning before the count is applied would move quantities nobody has verified. | |
| RETC-02 **[critical]** | Apply the reconciliation | **Return All Counted Stock** appears, and an info box explains the choice. The **Return** column appears on the lines. | |
| RETC-03 | Press **Return All Counted Stock** | Return column fills with each line's counted quantity; **To Return** totals it | |
| RETC-04 **[critical]** | Press **Create Return Transfer** | A van return transfer opens: source the van location, destination `WH/Stock`, one line per returned product, state **Ready** — **not validated**. Origin is the reconciliation reference. | |
| RETC-05 | On that transfer, Additional Info tab | **Van Operation = Van Return** and **From Reconciliation** points back | |
| RETC-06 | Validate it as the warehouse | Van stock drops to zero for those products; warehouse stock rises | |
| RETC-07 | Back on the reconciliation → **Return Transfer** stat button | Opens the transfer | |
| RETC-08 | Press **Create Return Transfer** again | *"… already has the return transfer …. Cancel it first if you need to raise another."* | |
| RETC-09 | Cancel that transfer, then press Create Return Transfer again | Allowed — a cancelled return does not block a new one | |
| RETC-10 **[critical]** | Apply a reconciliation and press **Create Return Transfer** without setting any quantities | *"No quantity is marked for return. Use Return All Counted Stock, or type quantities in the Return column."* **Nothing is created** — the column defaults to zero on purpose. | |
| RETC-11 | Type a Return quantity **higher** than Counted | Blocked: *"You cannot return … only … were counted on the van."* | |
| RETC-12 | Type a negative Return quantity | Blocked | |
| RETC-13 | Set Return on only two of five products, create the transfer | Only those two lines appear. Partial returns work — the rest stays on the van. | |
| RETC-14 | Press **Keep All On Van** | Return column clears; the Create button disappears | |
| RETC-15 | As `van.suresh` (Supervisor), open an applied reconciliation | The return buttons are not available — Administrator only | |
| RETC-16 **[dev]** | Shell: call `action_create_return_picking()` on a **draft** reconciliation | *"Apply the count before returning stock…"* — the guard is on the server, not just the button | |
| RETC-17 | Van form → **Return Stock** (the manual path) | Still works exactly as before, unchanged | |

---

## 7. Security — SEC

| ID | Steps | Expected | Result |
|---|---|---|---|
| SEC-01 **[critical]** | Log in as `van.rashid` (Van Sales User, drives GF-1234) → Van Sales → Van Loads | Sees **only** GF-1234's transfers. Anil's and Joseph's are invisible. | |
| SEC-02 | `van.rashid` opens one | Read only — he cannot validate or edit | |
| SEC-03 | `van.rashid` → Reconciliations | Sees only reconciliations for his own van, read only | |
| SEC-04 | `van.rashid` looks for an Apply button | Not available to him | |
| SEC-05 **[critical]** | `van.suresh` (Supervisor) → Van Loads | Sees **every van's** transfers | |
| SEC-06 | `van.suresh` → a van form | Can press **Reconcile Stock**; **Load Van** and **Return Stock** are not available (Administrator only) | |
| SEC-07 | `van.suresh` presses Apply on a reconciliation | Blocked: *"Only a Van Sales Administrator can apply a stock reconciliation."* | |
| SEC-07a | `van.suresh` tries to raise a return | Blocked: *"Only a Van Sales Administrator can raise a van return."* | |
| SEC-08 **[critical]** | `van.fatima` (Administrator) | Can load, return, reconcile and apply | |

---

## 8. Inventory regression — STK

**Do not skip.** This module adds record rules to `stock.picking`. These cases
prove it changed nothing for existing Inventory users.

| ID | Steps | Expected | Result |
|---|---|---|---|
| STK-01 **[critical]** | Create a user with **Inventory / User** and **no** Van Sales role. Log in → Inventory → Transfers. | Sees **every** transfer, van ones included, exactly as before this module | |
| STK-02 **[critical]** | Give that same user the Van Sales **User** role as well. Reload. | **Report exactly what they can now see.** This is the combination most at risk. | |
| STK-03 | Inventory → Transfers, default columns | Unchanged. Van columns exist only under the optional-columns toggle. | |
| STK-04 | Transfer form for a non-van transfer | Unchanged — no Van Sales group, no alert | |
| STK-05 | Inventory search panel | Existing filters intact; new *Van Loads*, *Van Returns*, *With Discrepancy* present | |
| STK-06 | Receipts, Deliveries, backorders, returns, scrap on ordinary warehouse transfers | All still work | |
| STK-07 | Product form for a non-storable product (a service) | The Van Sales group on the Inventory tab is hidden | |

---

## 9. Edge cases — EDGE

| ID | Steps | Expected | Result |
|---|---|---|---|
| EDGE-01 | **Load Van** on a vehicle that is not marked as a sales van | *"… is not marked as a sales van."* | |
| EDGE-02 | **Load Van** on a sales van whose stock location was cleared | *"… has no van stock location yet."* | |
| EDGE-03 **[dev]** | Archive the warehouse's Internal Transfers operation type, then Load Van | *"The internal operation type of warehouse … is archived. Enable Storage Locations in Inventory settings…"* — a clear message, not a traceback | |
| EDGE-04 | Reconcile a van that has never been loaded | Opens with zero lines and no error | |
| EDGE-05 | Cancel a van load transfer, then reconcile | Cancelled moves are ignored — they never happened | |
| EDGE-06 | Reconcile twice in the same period, applying the first | The second shows the first's adjustment in **Written Off** or **Other In**, and System matches reality | |
| EDGE-07 | Two vans loaded with the same product | Each reconciliation sees only its own van's movements | |
| EDGE-08 **[dev]** | A product whose sale UoM differs from its stock UoM, loaded in the other unit | Reconciliation figures are in the **product's** unit throughout, correctly converted | |

---

## Out of scope — do not report as defects

- **Selling anything.** No orders, invoices or payments — that is `van_sales_sale`.
  Section 5 of the scenario shows how to simulate a sale at stock level.
- **Enforcement of the over-sell policy** (POL-08). Policy and check are here;
  the enforcement point is where a line is sold.
- **Free-of-charge split.** At stock level an FOC line and a sale both move goods
  to a customer location and are indistinguishable. FOC is counted inside
  **Sold** until the sales module supplies the flag.
- **Lot / expiry level reconciliation** — product level only, pending the lot
  tracking decision.
- **Where returned goods land** (saleable vs quarantine) — open decision.
- **Discrepancy reason codes** — free text until the client supplies a list.
- **Automatic reconciliation on a schedule** — started by hand.

## By design — flag with **?** if you disagree

1. **Counted is pre-filled from the system quantity** (REC-02). An untouched line
   adjusts nothing. The trade-off: this is *not* a blind count. If counters must
   not see the system figure, that needs a different entry flow.
2. **A van load is an ordinary internal transfer**, not a document of its own.
3. **Applied reconciliations cannot be cancelled or deleted** — the adjustments
   are already in the stock history. Correct with a new one.
4. **A Van Sales Administrator gets the Inventory User role** automatically.
5. **Storage Locations is switched on at install**, for everyone.
6. **Supervisors can reconcile but not apply**, and cannot load vans or raise returns.
7. **The return is a separate step from Apply**, and the Return column defaults
   to zero. If the client's vans always empty overnight and they would rather
   the return happened automatically on Apply, say so — it is a small change,
   but it would be wrong for any operation that leaves stock on the van.

## Reply template

```
ENVIRONMENT   Odoo 19 EE · database · fresh or continued from base testing
SUMMARY       run __ / 87   passed __   failed __   disagreements __
FAILURES      <ID>  what I did -> what I saw  (+ traceback)
DISAGREEMENTS <ID>  what I would prefer
ANYTHING ELSE behaviour that surprised you even if nothing broke
```
