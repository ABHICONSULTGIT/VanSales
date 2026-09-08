# Van Sales - Stock: Real-World Test Scenario

Module `van_sales_stock` `19.0.1.0.0`

**Wednesday at Gulf Fresh Distribution** — the day after the `van_sales_base`
scenario. Same company, same three vans, same people. Today they actually load
stock, sell it, bring the remainder back, and count what is left.

Run this instead of inventing data. `TESTING.md` is the checklist; this is the
story that produces it. Every step names the case IDs it covers.

Prerequisite: the base scenario master data exists (three vans with stock
locations, four routes, six users).

---

## The one thing that needs explaining first

`van_sales_sale` does not exist yet, so nothing can *sell*. But a sale, at stock
level, is only ever a move from the van's location to a customer location — so
you can produce exactly the same stock movement by hand:

> **Inventory → Operations → Deliveries → New**
> · Operation Type: **Delivery**
> · **Source Location: change it to the van's location**, e.g. `WH/Vans/GF-1234`
> · Destination Location: `Partners/Customers`
> · Add the products and quantities
> · Mark as Todo → Check Availability → Validate

That is byte-for-byte the move a real van sale will create. It is why the
reconciliation is built on `stock.move` rather than on sales documents: what you
test today is what will run in production, with nothing to rewire.

Steps below call this **"simulate a sale"**.

---

## 1. Set up the goods (once)

### 1.1 Categories

Inventory → Configuration → Product Categories:

| Category | Van Over-Sell Policy |
|---|---|
| Beverages | **Block** |
| Dairy | **Allow** |
| Snacks | leave at the default **Warn** |

*(POL-01, POL-02)*

### 1.2 Products

All **Goods** with **Track Inventory** ticked. Leave the unit as **Units** —
cartons vs pieces is still an open decision and mixing them now would muddy the
results.

| Product | Category |
|---|---|
| Water 500ml Pack | Beverages |
| Water 1.5L Pack | Beverages |
| Orange Juice 1L | Beverages |
| Laban 1L | Dairy |
| Potato Chips Box | Snacks |

Open **Water 500ml Pack → Inventory tab → Van Sales**.

> Policy is *Use Category Policy*, and **Effective Policy** reads **Block**,
> inherited from Beverages.
> *(POL-03)*

### 1.3 Warehouse stock

Inventory → Operations → Physical Inventory: 500 of each into `WH/Stock`, Apply.

---

## 2. 05:30 — the warehouse loads the vans (as **Fatima**)

**Step 1.** Van `GF-1234` → **Van Sales** tab → **Load Van**.

> A transfer opens already pointed the right way: Source `WH/Stock`,
> Destination `WH/Vans/GF-1234`.
> *(LOAD-01)*

Load Rashid's van: 120 Water 500ml, 60 Water 1.5L, 40 Juice, 30 Laban,
25 Chips. Mark as Todo → Check Availability → **Validate**.

> Additional Info tab shows **Van Operation = Van Load**, **Van = GF-1234**,
> **Salesman = Rashid Kamal**. Nobody typed any of that.
> *(LOAD-02)*

**Step 2.** Van form → **Van Stock** stat button.

> The five products, in the van's own location.
> *(LOAD-03)*

**Step 3.** Load Anil's van `GF-5678` — but this time the deliberately awkward
way: **Inventory → Operations → Internal Transfers → New**, and set the
destination to `WH/Vans/GF-5678` by hand. 100 Water 500ml, 50 Juice. Validate.

> Recognised as a **Van Load** with no extra step. This is the point of
> classifying from the locations: the warehouse team's existing habits keep
> working.
> *(LOAD-05)*

**Step 4.** Load Joseph's mobile shop `GF-9012`: 200 Water 500ml, 80 Juice,
50 Chips.

**Step 5 — the short load.** A second run out to Rashid: demand 40 Chips, but
only 35 fit. On the Operations tab set the done quantity to **35**, validate,
choose **No Backorder**.

> An orange alert: the quantity received differs by **-5**.
> On the Additional Info tab, **Discrepancy Reason** has appeared. Enter
> `Only 35 boxes fitted after the drinks were loaded`.
> *(DISC-01, DISC-02)*

**Step 6.** Check a load that is still in Ready state, part-picked.

> **No alert.** Before validation the gap is work in progress, not a
> discrepancy.
> *(DISC-05)*

**Step 7.** Van Sales → Operations → **Van Loads**.

> All four loads, grouped by van.
> *(LOAD-06)*

---

## 3. 07:00 — Rashid checks his van (as **van.rashid**)

**Step 8.** Van Sales → Operations → Van Loads.

> He sees **only GF-1234's** loads. Anil's and Joseph's are invisible.
> Open one — read only.
> *(SEC-01, SEC-02)*

---

## 4. Through the day — selling

Use the recipe at the top. These simulate what `van_sales_sale` will do.

**Step 9.** Rashid sells on the north round — one delivery out of
`WH/Vans/GF-1234` to `Partners/Customers`: 45 Water 500ml, 20 Water 1.5L,
15 Juice, 12 Laban, 10 Chips. Validate.

**Step 10.** Joseph sells at the labour camp — out of `WH/Vans/GF-9012`:
150 Water 500ml, 55 Juice, 35 Chips. Validate.

**Step 11 — breakage.** Two Laban cartons split in Rashid's van.
Inventory → Operations → Physical Inventory, filter to `WH/Vans/GF-1234`,
set Laban's counted quantity **2 lower**, Apply.

> This produces a move to the inventory-loss location — which the reconciliation
> will report separately, in **Written Off**.
> *(REC-09)*

---

## 5. 17:30 — stock comes back (as **Fatima**)

**Step 12.** Van `GF-1234` → **Return Stock**. Send back 20 Water 500ml and
15 Chips. Validate.

> **Van Operation = Van Return**.
> *(RET-01, RET-02)*

**Step 13.** Anil's van broke down and Joseph took over his remaining stock.
Internal transfer `WH/Vans/GF-5678` → `WH/Vans/GF-9012`, 30 Water 500ml.
Validate.

> **Van to Van**, with *From Van* and *To Van* both filled. The **Van** field
> shows the receiving van.
> *(RET-04, RET-05)*

---

## 6. 18:00 — counting the vans (as **Fatima**)

**Step 14.** Van `GF-1234` → **Reconcile Stock**.

> `VREC/<year>/0001` opens in Draft, period midnight → now, lines already
> generated.
> *(REC-01)*

**Step 15.** Read one line across — say Water 500ml:

| Column | Should show |
|---|---|
| Opening | 0 (the van started empty) |
| Loaded | 120 |
| Sold / Delivered | 45 |
| Returned | 20 |
| Written Off | 0 |
| System | 55 |
| Counted | **55, pre-filled** |
| Difference | 0 |

> Check the arithmetic: `0 + 120 − 45 − 20 − 0 = 55`. It balances exactly,
> because Opening is derived from the movements rather than guessed.
> The Laban line should show 2 in **Written Off**.
> *(REC-02, REC-07, REC-08, REC-09, REC-10)*

**Step 16.** Press **Apply** without touching anything.

> Applied, and **nothing in stock changes**. This is the safety property worth
> proving: a line nobody counted adjusts nothing. Had Counted defaulted to
> zero, this single click would have written off the entire van.
> *(REC-03)*

**Step 17 — the real count.** Start another reconciliation on `GF-1234`. Rashid
counts the van and finds **52** Water 500ml, not 55.

Change Counted to 52 → **Apply**.

> Difference **-3**. Inventory → Reporting → Moves History shows an adjustment
> of -3 out of the van location. The chatter records how many products were
> adjusted.
> *(REC-04, REC-05)*

**Step 18.** Reconcile `GF-9012`.

> Its figures include the 30 Water 500ml received from Anil's van as **Other
> In**, not as Loaded — it came from another van, not the warehouse.

**Step 19.** Try to delete the applied reconciliation.

> *"An applied reconciliation cannot be deleted, because the inventory
> adjustments it made are already in the stock history…"*. Try Cancel — refused
> for the same reason.
> *(REC-17, REC-18)*

---

## 7. Things that go wrong — run these too

**Scenario A — someone moved stock while you were counting.**
Open a fresh reconciliation on `GF-1234` and generate lines. **Before applying**,
in another tab, transfer 5 Water 500ml out of that van. Now Apply.

> The adjustment **still lands**, and the van ends at the quantity you counted.
> Odoo's own public method silently does nothing in this situation and returns
> a dialog instead — this module deliberately does not use it. If the
> adjustment is missing, that is a serious finding.
> *(REC-23)*

**Scenario B — the salesman shouldn't be able to correct stock.**
As `van.suresh` (Supervisor), open a reconciliation and press **Apply**.

> *"Only a Van Sales Administrator can apply a stock reconciliation."*
> He can create and count; only the office applies.
> *(SEC-07)*

**Scenario C — an Inventory user who has nothing to do with van sales.**
Create a user with **Inventory / User** and no Van Sales role. Log in →
Inventory → Transfers.

> They see **every** transfer, van ones included, exactly as before this module
> was installed. Now add the Van Sales **User** role to that same person and
> look again — **report exactly what they can see**. This is the combination
> most at risk, for the same reason as the Fleet check in the base scenario.
> *(STK-01, STK-02)*

**Scenario D — a van with nothing on it.**
Reconcile `GF-5678` after everything went to Joseph.

> Opens cleanly, System zero or near it, no error.
> *(EDGE-04)*

**Scenario E — over-selling.**
Rashid's van holds 52 Water 500ml. Simulate a sale of 60.

> Odoo lets it through and the van goes negative. **This is expected today**:
> the policy and the check exist, but the enforcement point is where a line is
> sold, in `van_sales_sale`. Report it only if you expected otherwise.
> *(POL-08)*

**Scenario F — a cancelled load.**
Create a van load, then cancel it before validating. Reconcile.

> Cancelled moves are ignored. They never happened.
> *(EDGE-05)*

**Scenario G — the warehouse's own work.**
Do an ordinary receipt and an ordinary delivery from `WH/Stock`.

> No Van Sales group, no alert, no reclassification. Non-van transfers are
> untouched.
> *(LOAD-07, STK-04, STK-06)*

---

## 8. What this scenario does not cover

Not missing — not built:

- Orders, invoices, payments, credit, FOC (`van_sales_sale`)
- Enforcement of the over-sell policy
- Lot / expiry tracking and expiry-based returns
- The mobile app confirming loads in the field
- Automatic end-of-day reconciliation on a schedule

One limitation to understand rather than report: **free-of-charge goods are
counted inside Sold**. At stock level an FOC line and a sale both move goods to
a customer location and are indistinguishable. The split needs the FOC flag,
which lives in the sales module.

---

## 9. Coverage map

| Section | Covered by the scenario | Still to test separately |
|---|---|---|
| INST | — | INST-01 … 07 |
| POL | 01, 02, 03, 08 | 04, 05, 06, 07 |
| LOAD | 01, 02, 03, 05, 06, 07 | 04, 08, 09 |
| RET | 01, 02, 04, 05 | 03 |
| DISC | 01, 02, 05 | 03, 04, 06 |
| REC | 01, 02, 03, 04, 05, 07, 08, 09, 10, 17, 18, 23 | 06, 11 … 16, 19 … 22, 24, 25 |
| SEC | 01, 02, 07 | 03, 04, 05, 06, 08 |
| STK | 01, 02, 04, 06 | 03, 05, 07 |
| EDGE | 04, 05 | 01, 02, 03, 06, 07, 08 |

Run the story first — it is faster and it surfaces the problems that matter.
Then sweep the right-hand column, which is mostly negative cases.

## 10. Reporting back

Give me the **step number** as well as the case ID. The step says what the
business was trying to do, which is usually more useful than the assertion that
broke. Server-log tracebacks are the single most useful thing you can send:
paste from `Traceback (most recent call last)` to the last line.

If a step felt wrong *as a business flow* even though nothing errored, say so —
that is the most valuable feedback there is.
