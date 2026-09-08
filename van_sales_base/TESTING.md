# Van Sales - Base: Unit / UAT Test Guide

Module `van_sales_base` version `19.0.1.2.0` · Odoo 19 Enterprise

Every case below is written against the actual code — the expected messages are
quoted verbatim from the source, so if you see different wording, that itself is
a finding worth reporting.

---

## How to use this

Work top to bottom. Sections build on each other: **VAN** creates the vans that
**RTE** needs, **RTE** creates the routes that **PLAN** needs.

For each case record one of:

- **P** — passed, behaved exactly as the Expected column says
- **F** — failed, plus what you actually saw
- **?** — behaved as described but you disagree with the design
- **N/A** — could not test (say why)

When you reply, **only the F and ? rows matter**. Just the IDs plus one line
each is enough — for example:

```
VAN-04  F  location was called "Van False" not "Van 12"
PLAN-01 ?  stops came out alphabetical, we need route order
SEC-08  ?  supervisors should be able to edit routes
```

Cases marked **[critical]** are the ones that must pass before this module is
worth reviewing further. Cases marked **[dev]** need developer mode or the shell
and can be skipped on a first pass.

---

## 0. Setup

### 0.1 Install

1. Add the module directory to `addons_path` in `odoo.conf`:

   ```
   addons_path = .../odoo19/all_addons,
                 .../odoo19/custom_addons/AlsayahPharmacyJul30,
                 .../odoo19/custom_addons/VanSales
   ```

2. Restart Odoo, **Apps → Update Apps List**, install **Van Sales - Base**.
3. Keep the server log open in a terminal for the whole session. Warnings during
   install matter as much as visible errors.

Use a **throwaway database**. Several cases deliberately create bad data.

### 0.2 Test data to create first

| What | Details |
|---|---|
| Warehouse | The default `WH` is fine. Note its Short Name. |
| Customers | At least 4 contacts: `Test Cust A` … `Test Cust D` |
| Stop locations | Van Sales → Configuration → Stop Locations: `Friday Market`, `Labour Camp 3`, `North Junction` |
| Cash journal | Accounting → Configuration → Journals → one of type Cash |
| Vehicle model | Fleet needs a model on every vehicle. Create brand `TestBrand`, model `TestVan`. |
| Users | `van.user1`, `van.user2` (Van Sales → User: Own Van Only), `van.super` (Supervisor), `van.admin` (Administrator), `fleet.only` (Fleet → Officer, **no** Van Sales role) |

Enable **Settings → Inventory → Storage Locations** so you can see the location
tree.

---

## 1. Installation — INST

| ID | Steps | Expected | Result |
|---|---|---|---|
| INST-01 **[critical]** | Install the module | Installs with no error and no traceback in the log | |
| INST-02 | Look at the top menu | **Van Sales** app appears with a van icon | |
| INST-03 | Open it | `Operations → Visit Plans, Visits` and `Configuration → Sales Vans, Routes` | |
| INST-04 | Settings → Users & Companies → Groups | A **Van Sales** privilege with exactly 3 groups: *User: Own Van Only*, *Supervisor: All Vans*, *Administrator* | |
| INST-05 | Settings → Technical → Sequences | A sequence named **Van Sales Route**, prefix `R`, padding 5 | |
| INST-06 | Upgrade the module a second time (`-u van_sales_base`) | Clean upgrade, no duplicated records, no errors | |
| INST-07 | Uninstall, then reinstall | Uninstalls cleanly; reinstall works | |

---

## 2. Van creation and automatic stock location — VAN

This is the section you asked for. VAN-01 is the headline case.

| ID | Steps | Expected | Result |
|---|---|---|---|
| VAN-01 **[critical]** | Van Sales → Configuration → Sales Vans → **New**. Set Model = `TestVan`, Plate = `VAN-001`. **Save**. | **Sales Van** is already ticked. **Van Sales** tab shows *Loading Warehouse* prefilled and *Van Stock Location* = `WH/Vans/VAN-001`. **No** orange warning banner. | |
| VAN-02 | Inventory → Configuration → Locations, clear filters | `WH/Vans` exists with type **View**; `WH/Vans/VAN-001` exists with type **Internal** and the right company | |
| VAN-03 | Create a second van `VAN-002` | Same `WH/Vans` parent reused — **not** a second "Vans" location | |
| VAN-04 | Create a van with Model set but **Plate left empty** | Location is named `Van <id>` (the vehicle's database id) | |
| VAN-05 | On that van, now set Plate = `VAN-003` and save | Location is **renamed** to `VAN-003`; the vehicle chatter logs the rename | |
| VAN-06 | On another van, manually rename its location to `My Own Name`, then change the vehicle's plate | Location is **NOT** renamed. (Proves the rename only touches names this module generated.) | |
| VAN-07 **[critical]** | Fleet app → Vehicles → New. Do **not** tick Sales Van. Save. | **No** stock location created, no `Vans` child added, no Van Sales tab visible | |
| VAN-08 | On that same vehicle, tick **Sales Van** and save | Location created now | |
| VAN-09 | Create a van with a plate that duplicates an existing one | Second location is named `VAN-001 (id)` — no crash, no clash | |
| VAN-10 | Open any auto-provisioned van's chatter | Message: *"Van stock location … created."* | |
| VAN-11 | On a van, change **Loading Warehouse** to a second warehouse **before** first save | Location created under **that** warehouse's `Vans` | |
| VAN-12 | Van form → stat buttons | **Routes** shows 0; **Van Stock** opens an empty stock-quant list filtered to that location | |
| VAN-13 | Duplicate a sales van (Action → Duplicate) | New vehicle gets **its own new** location; salesman is *not* copied | |
| VAN-14 | Import 2 vehicles via Import with `is_sales_van = True` | Both get their own locations | |

---

## 3. Van constraints — VANC

| ID | Steps | Expected | Result |
|---|---|---|---|
| VANC-01 **[critical]** | Set salesman `van.user1` on van A. Save. Now set the same salesman on van B. Save. | Blocked: *"… is already assigned to van … A salesman can operate only one van at a time…"* | |
| VANC-02 | On van B, set *Van Stock Location* to van A's location | Blocked: *"This stock location is already used by another active sales van…"* | |
| VANC-03 | Archive van A, then assign `van.user1` to van B | **Allowed** — the constraint only counts active vans | |
| VANC-04 | Clear van A's *Van Stock Location* and save | Allowed; the orange **setup warning banner** reappears with a *Create Van Stock Location* button | |
| VANC-05 | Click that button, complete the wizard | Location created and assigned; banner gone | |
| VANC-06 **[dev]** | Via shell, set `van_location_id` to a **View**-type location | Blocked: *"…must be an internal location…"* | |

---

## 3b. Stop locations — STOP

New in `19.0.1.2.0`. A stop location is a *place* the van parks and sells from,
as opposed to a named customer.

| ID | Steps | Expected | Result |
|---|---|---|---|
| STOP-01 **[critical]** | Van Sales → Configuration → Stop Locations → New. Name = `Friday Market`, City = anything. Save. | Saves cleanly | |
| STOP-02 | Add Code `FM-01`, latitude/longitude, notes | All save; the record displays as `[FM-01] Friday Market` | |
| STOP-03 | Create a second location with the same code `FM-01` | Blocked: *"A stop location with this code already exists for this company."* | |
| STOP-04 | Create two locations both with **no** code | Both save — the code uniqueness only applies when a code is set | |
| STOP-05 | Archive a location | Disappears from the list; visible under **Archived** | |
| STOP-06 | Search filter **Not On Any Route** | Lists only locations not used on a route | |
| STOP-07 | Stat button **Visits** on a location that has been visited | Opens that location's visits | |

## 4. Routes — RTE

| ID | Steps | Expected | Result |
|---|---|---|---|
| RTE-01 **[critical]** | Van Sales → Configuration → Routes → New. Name = `North City`. **Leave the code as "New"**. Assign van `VAN-001`. Save. | Code becomes **`R00001`** | |
| RTE-02 | Create a second route the same way | Code becomes `R00002` | |
| RTE-03 | Create a third route and type your own code `NORTH-1` | Your code is kept, sequence not used | |
| RTE-04 | Create a route with a code that already exists | Blocked: *"A route with this code already exists for this company."* | |
| RTE-05 | Look at the **Salesman** field | Read-only, shows the van's salesman. Change the van's salesman → route follows. | |
| RTE-06 | Assign a van whose *Van Stock Location* is empty (see VANC-04) | Blocked: *"Van … has no stock location yet, so it cannot be assigned to route…"* | |
| RTE-07 **[critical]** | Leave **Route Type** = *Customer Route*. On the **Stops** tab add customers A, B, C. Save. | Each line defaults to Stop Type **Customer**; the Customer column is shown and the Stop Location column stays blank | |
| RTE-08 | Add customer A a second time | Blocked: *"This customer is already on this route."* | |
| RTE-08a **[critical]** | New route, **Route Type = Location Route**. Add stops `Friday Market`, `Labour Camp 3`. Save. | New lines default to Stop Type **Location**; the Stop Location column is shown, Customer stays blank | |
| RTE-08b | On that route add `Friday Market` a second time | Blocked: *"This stop location is already on this route."* | |
| RTE-08c **[critical]** | On a Customer Route, add one line and switch its Stop Type to **Location**, pick a place. Save. | **Allowed** — a mixed route is permitted. Say if the client wants this forbidden. | |
| RTE-08d | On a line, set a customer, then switch Stop Type to Location | The customer clears itself; you are asked for a location instead | |
| RTE-08e **[dev]** | Force a line with both a customer and a location | Blocked: *"A customer stop cannot also carry a stop location."* | |
| RTE-09 | Drag the handle to reorder to C, A, B. Save. Reopen. | New order persists | |
| RTE-10 | Type something in the **Instructions** column | Saves per customer line | |
| RTE-11 | Archive the route | Disappears from the list; visible under the **Archived** filter | |
| RTE-12 | Create a route with no van, or with no customers | The **Plan Today's Visits** button is hidden | |
| RTE-13 | Search view: *My Routes*, *Customer Routes*, *Location Routes*, *No Van*; group by Route Type / Van / Salesman | All work | |
| RTE-14 | Route list columns | *Route Type* and *Stops* shown; *Customer Stops* / *Location Stops* available as optional columns | |

---

## 5. Visit plans — PLAN

| ID | Steps | Expected | Result |
|---|---|---|---|
| PLAN-01 **[critical]** | Open route `R00001` (with 3 customers) → **Plan Today's Visits** | A plan opens: state **Draft**, date today, Reference `R00001 / <today>`, and **3 stops already generated in route order** | |
| PLAN-02 | Press **Plan Today's Visits** on the same route again | Opens the **same** plan — no duplicate, no extra stops | |
| PLAN-03 **[critical]** | Van Sales → Operations → Visit Plans → New. Pick route + tomorrow's date. Save. | Stops **auto-generated on save** | |
| PLAN-04 | Create a plan for a route that has **no** stops | Saves with 0 stops and **no error** | |
| PLAN-04a **[critical]** | Plan a **Location Route** | Stops generated as location stops, in route order, each showing the place not a customer | |
| PLAN-04b | Plan a **mixed** route | Both kinds appear in one plan, in sequence | |
| PLAN-05 | Create a second plan, same route, same date | Blocked: *"A visit plan already exists for this route on this date."* | |
| PLAN-06 | Add customer D to the route, then press **Generate Stops** on the existing draft plan | Only D is added; the existing 3 stops are untouched | |
| PLAN-07 | Press **Generate Stops** on a plan whose route has no stops | *"Route … has no stops, so there is nothing to plan."* | |
| PLAN-08 | On a 0-stop plan press **Start Day** | *"Plan … has no visits yet. Generate the stop list first."* | |
| PLAN-09 | On a 3-stop plan press **Start Day** | State → **In Progress**; Route and Date become read-only | |
| PLAN-10 | Press **Close Day** while one stop is still Checked In | *"Check out of these stops before closing the plan: …"* | |
| PLAN-11 | Check out everything, then **Close Day** | State → **Done** | |
| PLAN-12 | On a Draft plan press **Close Day** | *"Only a plan in progress can be closed…"* | |
| PLAN-13 | **Cancel** a plan, then **Reset to Draft** | Cancelled → Draft works | |
| PLAN-14 | On a **Done** plan press Reset to Draft | *"Only a cancelled plan can be reset to draft…"* | |
| PLAN-15 | Delete a **Done** plan | *"A visit plan can only be deleted while it is draft or cancelled…"* | |
| PLAN-16 | Delete a **Draft** plan | Deleted, and its stops go with it | |
| PLAN-17 | Watch the counters as you work | *Planned / Completed / Pending* update correctly | |
| PLAN-18 | Visit Plans list, try the **Today** filter and group by Route / Salesman / Status | All work | |

---

## 6. Visits — VIS

| ID | Steps | Expected | Result |
|---|---|---|---|
| VIS-01 **[critical]** | On a **Draft** plan, press **Check In** on the first stop | Stop → Checked In with a timestamp, **and the plan moves itself to In Progress**, with a chatter note on the plan saying so | |
| VIS-02 **[critical]** | Press **Check Out** | Stop → Done; **Duration (minutes)** computed | |
| VIS-03 | Press Check In again on the same stop | *"Only a planned stop can be checked into…"* | |
| VIS-04 | Press Check Out on a stop never checked into | *"Only a stop that has been checked into can be checked out of…"* | |
| VIS-05 | Press **Skip** with no reason filled | *"Give a reason before skipping …"* | |
| VIS-06 | Fill *Reason for Skipping*, press Skip | State → Skipped, row greys out | |
| VIS-07 | Press Skip on a **Done** stop | *"… is done and cannot be skipped."* | |
| VIS-08 | Add a stop by hand on an In Progress plan, tick **Unplanned Visit**, leave the reason empty, save | Blocked: *"An unplanned visit needs a reason…"* | |
| VIS-08a **[critical]** | On a Location Route plan, the salesman adds an unplanned **location** stop mid-route | Allowed — this is the free-selling case the client described | |
| VIS-08b | On the same plan, add an unplanned **customer** stop | Allowed — a known shop met on a free route | |
| VIS-08c | Check in / out on a location stop | Works exactly as for a customer stop; duration computed | |
| VIS-09 | Same but with a reason | Saves; check in / out works normally | |
| VIS-10 | Close the plan, then try Check In on any of its stops | *"Plan … is done, so its stops cannot be visited."* | |
| VIS-11 | As **Supervisor**, press **Reset to Planned** on a Done stop | Back to Planned, timestamps and GPS cleared | |
| VIS-12 | As **User**, look for that button | Not visible (supervisor-only) | |
| VIS-13 | Visits list → check the Duration column total | Sums correctly | |
| VIS-14 | Visits list → filters *My Visits*, *Today*, *Planned/Checked In/Done/Skipped*, *Unplanned*; group by *Stop Location* and *Stop Type* | All work | |
| VIS-15 **[dev]** | Via shell, write a check-out earlier than the check-in | Blocked: *"Check-out cannot be earlier than check-in…"* | |
| VIS-16 **[dev]** | Via shell, write `check_in_latitude = 120` | Blocked by the range constraint | |

---

## 7. Security and roles — SEC

Log in as each user in a private window so sessions do not collide.

| ID | Steps | Expected | Result |
|---|---|---|---|
| SEC-01 **[critical]** | `van.user1` (User role, salesman of van A) → Van Sales app | Sees **Operations** only. **No Configuration menu.** | |
| SEC-01a | `van.user1` opens a location stop on their plan | Can read the stop location name; cannot create or edit stop locations | |
| SEC-02 **[critical]** | `van.user1` → Visit Plans / Visits | Sees only plans and stops for **their own** van. Van B's are invisible. | |
| SEC-03 | `van.user1` opens a stop | Can Check In / Check Out / Skip | |
| SEC-04 | `van.user1` tries to delete a visit | Not permitted | |
| SEC-05 | `van.user1` creates an ad-hoc stop on their own plan | Allowed | |
| SEC-06 | `van.super` (Supervisor) | Sees **all** vans, routes, plans and visits; can create plans; can Reset to Planned | |
| SEC-07 | `van.super` → Configuration menu | **Not visible** (Administrator only). *Tell me if supervisors should configure routes — this is a design call, not a defect.* | |
| SEC-08 | `van.admin` (Administrator) | Full access: creates vans, provisions locations, creates routes | |
| SEC-09 | `van.user1` opens the location provisioning wizard (if reachable) | Blocked: *"Only a Van Sales Administrator can provision van stock locations."* | |
| SEC-10 | `van.user1` opens their own van record | Can read it, **cannot** edit it | |

---

## 8. Fleet regression — FLT

**Do not skip this section.** The module adds a record rule to `fleet.vehicle`,
and this proves it changed nothing for existing Fleet users.

| ID | Steps | Expected | Result |
|---|---|---|---|
| FLT-01 **[critical]** | Log in as `fleet.only` (Fleet Officer, **no** Van Sales role) → Fleet → Vehicles | Sees **every** vehicle, including all sales vans | |
| FLT-02 **[critical]** | Give `fleet.only` the Van Sales *User* role as well, reload | Still behaves sensibly — say exactly what they can see, this is the combination most at risk | |
| FLT-03 | Fleet vehicle **list** view, default columns | Unchanged. The van columns exist only under the optional-columns toggle (⚙ top right). | |
| FLT-04 | Fleet vehicle **form** on a non-sales vehicle | Unchanged apart from a **Sales Van** checkbox in the Vehicle group. No Van Sales tab. | |
| FLT-05 | Fleet vehicle **search** panel | Existing filters intact; new *Sales Vans* and *Missing Van Location* filters present | |
| FLT-06 | Odometer, Contracts, Services on a vehicle | All still work | |
| FLT-07 | Fleet → Vehicles → create, archive, delete | All still work | |

---

## 9. Edge cases — EDGE

| ID | Steps | Expected | Result |
|---|---|---|---|
| EDGE-01 **[critical]** | In a company with **no warehouse**, create a sales van | **No crash.** Van saves, no location, orange warning banner shown. | |
| EDGE-02 | Create a warehouse, then use the wizard on that van | Location created | |
| EDGE-03 | Run the wizard on vans that already have locations | *"Every selected vehicle already has a van stock location. Nothing to do."* | |
| EDGE-04 | Select several vehicles in the Fleet list → Actions ⚙ → *Create Van Stock Locations* | Wizard opens pre-filled with the selection; provisions only the ones missing a location | |
| EDGE-05 | Archive a sales van | Location remains (by design — it may still hold stock) | |
| EDGE-06 | Delete a route that has visit plans | Should be blocked by `ondelete='restrict'` — confirm the message is understandable | |
| EDGE-07 | Rapidly create 5 sales vans in a row | 5 distinct locations, no name clashes, one `Vans` parent | |

---

## 10. Multi-company — MC (only if you run multi-company)

| ID | Steps | Expected | Result |
|---|---|---|---|
| MC-01 | Create a van in company A, try to set a warehouse from company B | Blocked with a company-mismatch message | |
| MC-02 | As a user of company A only, list routes | Company B's routes invisible | |
| MC-03 | Create vans in both companies | Each gets a `Vans` parent under **its own** warehouse | |

---

## Out of scope — please do not report these as defects

These are not built yet, by plan:

- **Visit frequency / automatic daily plan generation.** Waiting on your
  confirmation of the frequency model. Plans are created explicitly today.
- **Who the invoice is made out to on a walk-up sale.** Stop locations exist,
  but nothing invoices yet. Odoo requires a partner on a posted customer
  invoice, so this needs an answer before `van_sales_sale` — see the open
  questions in the chat thread.
- **Van stock movements** — loading, GRN, unloading, reconciliation
  (`van_sales_stock`).
- **Orders, invoices, payments, FOC, returns, credit limits**
  (`van_sales_sale`).
- **Mobile synchronisation API** (`van_sales_sync`).
- **Statement of Account, dashboards, maps, notifications.**
- **GPS coordinates** are stored but nothing writes them yet — the mobile app
  will. In the backend they stay empty, which is correct.

## By design, but worth a second opinion

Flag these with **?** if you disagree — they are judgement calls, not bugs:

1. **Checking into the first stop starts the plan automatically** (VIS-01). The
   alternative is forcing Start Day first. It is logged on the chatter, never
   silent.
2. **Plans do not auto-close** when every stop is done. Deliberate: a salesman
   may still add an unplanned stop, and stops need a plan in progress.
3. **Route code sequence can leave gaps** if a save is rolled back. `no_gap`
   would take a row lock on every allocation for what is only an internal label.
4. **Anyone who can tick Sales Van causes a stock location to be created** —
   creation runs with elevated rights because it needs Inventory Administrator.
   Bounded to one fixed parent, one usage, one derived name.
5. **Archiving a van leaves its location behind** — it may still hold stock.
6. **Supervisors have no Configuration menu** (SEC-07).
7. **A salesman is limited to one van** (VANC-01), per section 10 of the
   requirement document.

## Housekeeping

`__pycache__` folders inside the module are leftovers from my syntax checks.
Harmless; delete them whenever convenient.

---

## Reply template

```
ENVIRONMENT
  Odoo build:            19.0 EE, <commit/date>
  Database:              fresh / existing
  Multi-company:         yes / no

SUMMARY
  Cases run:             __ of 100
  Passed:                __
  Failed:                __
  Design disagreements:  __

FAILURES
  <ID>  what I did  ->  what I saw  (log excerpt if there was a traceback)

DESIGN DISAGREEMENTS
  <ID>  what I would prefer instead

ANYTHING ELSE
  Behaviour that surprised you even if it did not break, and anything the
  business flow needs that is not covered by a case above.
```

Server-log tracebacks are the most useful thing you can send me — paste the
whole block from `Traceback (most recent call last)` down to the last line.
