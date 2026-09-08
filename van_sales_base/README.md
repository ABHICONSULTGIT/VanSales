# Van Sales - Base (`van_sales_base`)

Foundation module of the Van Sales suite for **Odoo 19 Enterprise**.

This module delivers items C-01, C-02, C-05 and C-06 of the development plan in
full, and C-03 partially (see *Deliberately absent* below).

## Installation

The module lives in a new addons directory. Add it to `odoo.conf`:

```
addons_path = .../odoo19/all_addons,
              .../odoo19/custom_addons/AlsayahPharmacyJul30,
              .../odoo19/custom_addons/VanSales
```

Then restart Odoo, update the apps list, and install **Van Sales - Base**.
It pulls in `stock`, `fleet` and `account` as dependencies.

## What it provides

### Van master (extends `fleet.vehicle`)

A sales van is a Fleet vehicle, not a parallel record. The module adds:

| Field | Purpose |
|---|---|
| `is_sales_van` | Separates sales vans from the company's other vehicles |
| `van_location_id` | The van's internal stock location - the authoritative anchor |
| `salesman_user_id` | The operating salesman, as a **`res.users`** |
| `cash_journal_id` | Where this van's cash collection posts |
| `van_route_ids` | Routes served by this van |

Note `salesman_user_id` is deliberately *not* fleet's `driver_id`: that field
points at `res.partner` and so cannot scope access rights or stamp documents.

Integrity is enforced at three levels:

* a **partial unique index** so one stock location backs at most one active
  sales van (holds against concurrent writes, not just the ORM);
* a Python constraint that the location is of type *internal*;
* a Python constraint that one salesman operates one van at a time, per section
  10 of the requirement document. Relax it only if the client confirms van
  sharing - van stock cannot be attributed to a person otherwise.

### Van stock location provisioning

Automatic on van creation (see *What happens automatically*). The
**Create Van Stock Locations** wizard remains for what automation deliberately
does not cover: vehicles that pre-date this module, vehicles whose warehouse
could not be resolved at creation time, and bulk provisioning into a warehouse
other than the vehicle's own. It creates `<Warehouse> / Vans / <Plate>` as an
internal location.

A location, **not a warehouse per van**: `stock.warehouse.create()` builds eight
picking types and eight `ir.sequence` records each - 800 picking types across a
100-van fleet - and gives nothing extra. `stock.location._compute_warehouse_id`
resolves the warehouse by walking `parent_path`, and
`stock_account`'s `_should_be_valued()` values any company-owned internal
location. Verified in the Odoo 19 source.

Because creating a `stock.location` requires *Inventory Administrator*, the
wizard creates it with `sudo()` behind an explicit
`group_van_sales_manager` check, rather than widening Inventory rights.

### Routes and stops

Confirmed with the client: the business runs **two models side by side**, and
the module supports both.

* **Customer Route** — a fixed round of known shops. Stops are `res.partner`
  records, which can carry credit limits, balances and statements.
* **Location Route** — the van parks at public places (a market, a labour camp,
  a junction) and sells to whoever walks up. Stops are
  `van.sales.stop.location` records.

`route_type` classifies the route and defaults the kind of stop; each stop line
also carries its own `stop_type`, so a route may **mix** the two. Nothing in
the requirement document says mixing is invalid, so it is not forbidden.

A stop location is a model of its own rather than a `res.partner`. Reusing a
partner is tempting — an invoice needs one, and the address and geo fields come
free — but it would put places into the customer list and muddy every customer
count. It also pre-empts an open question: who the invoice is made out to on a
walk-up sale. Keeping the place separate leaves that to `van_sales_sale`; a
link to a partner can be added here later if that turns out to be the answer.

The salesman is derived from the van, so there is a single source of truth.

A route cannot be assigned to a van that has no stock location - enforced at the
point it matters, so that ticking "Sales Van" before provisioning still works.

### Visit plans and visits

`van.sales.visit.plan` is one route on one date (unique). Its stops are
`van.sales.visit` records carrying check-in/check-out timestamps, GPS
coordinates and a computed duration.

Lifecycle: **Draft -> In Progress -> Done**, with Cancel and reset. Checking
into the first stop starts the day automatically and logs that on the plan's
chatter, so the state change is visible rather than silent.

`action_check_in` / `action_check_out` read optional
`van_sales_latitude` / `van_sales_longitude` context keys, so the same methods
serve the backend today and the mobile API later without change.

### Security

Three roles under the **Van Sales** privilege:

| Role | Sees |
|---|---|
| User: Own Van Only | Their own van, its routes, their own plans and stops |
| Supervisor: All Vans | Everything in the company; can create and correct plans |
| Administrator | Also configures vans, locations and routes |

Salesmen read `fleet.vehicle` without being granted the Fleet app, via a
targeted ACL plus a record rule.

**One deliberate extra rule:** Fleet ships no group-level record rule for
`fleet_group_user`, so a Fleet Officer currently sees every vehicle. Adding this
module's restrictive rule would silently narrow that for anyone who is both a
Fleet Officer and a plain Van Sales User, because group rules are OR-ed and only
matching rules count. `fleet_vehicle_fleet_officer_rule` restores Fleet's own
semantics explicitly, so installing this module changes nothing for existing
Fleet users.

## What happens automatically

Four things are automated. Each is idempotent, has a context opt-out, and
degrades to the manual path rather than failing.

| Automation | Trigger | Opt-out |
|---|---|---|
| Van stock location created and assigned | A vehicle is created with **Sales Van** ticked, or the tick is added later | `van_sales_no_autoprovision` |
| Van location renamed once the plate is known | The plate is set on a van whose location still carries the generated `Van <id>` name | - (only fires on that exact name) |
| Route code taken from a sequence | The code is left as **New** on save | Type your own code |
| Visit stops generated from the route | A visit plan is created | `van_sales_no_visit_generation` |

### Van stock location

The warehouse comes from **Loading Warehouse** on the vehicle, which defaults
to the first warehouse of the active company. That default is *visible on the
form before saving*, so with several warehouses the user corrects it rather
than discovering the wrong choice later. If no warehouse can be resolved,
nothing is created, the setup warning stays, and the wizard remains available -
the automation never fails a vehicle save.

Only vehicles with **Sales Van** ticked are touched. Ordinary Fleet vehicles
are created exactly as before.

Location creation runs `sudo()` because it needs Inventory Administrator, which
a Van Sales Administrator does not necessarily hold. The operation is tightly
bounded: one fixed parent, one fixed usage, one name derived from the plate.
Note this means anyone who can tick **Sales Van** causes an empty internal
location to be created - acceptable, but worth knowing.

### Route code

`R00001`, `R00002`, ... from the `van.sales.route` sequence, assigned **on
save** rather than on form open, so abandoned forms burn no numbers. The
sequence is `standard`, not `no_gap`: the code is an internal label, and
`no_gap` serialises every allocation against a row lock. Typing your own code
over `New` keeps it.

### Visit stops

Generating on create uses exactly the rule the **Generate Stops** button uses -
every customer on the route, in route order. No scheduling assumption is
introduced, because there is no frequency model to assume one from. A plan for
a route with no customers still saves; it simply has no stops.

## Deliberately NOT automated

These were considered and rejected. Each would have changed behaviour the
client has not signed off on.

| Candidate | Why not |
|---|---|
| **Auto-close the plan when every stop is done** | A salesman may add an unplanned stop after finishing the planned ones. Auto-closing would block that, because stops require a plan that is in progress. Closing the day stays a decision. |
| **Default the cash journal** | Per-van cash accountability is an open decision (D-08). Silently pointing every van at one shared journal would quietly defeat the per-van cash reconciliation the requirement document asks for. |
| **Default the salesman** | There is no rule to derive one from, and the one-salesman-one-van constraint makes a wrong guess a hard error at save. |
| **Archive the van location when the van is archived** | The location may still hold stock. Hiding it would hide the stock. This wants a *validation* once van stock exists (`van_sales_stock`), not an automation now. |
| **Clear the location when Sales Van is unticked** | Same reason: the link would be lost while stock is still sitting in the location. |
| **Add a new route customer to today's open plan** | Defensible either way, which is exactly why it should not happen silently. |

## Trying the business flow in the backend

1. **Van Sales > Configuration > Sales Vans > New** - fill the model (required
   by Fleet) and the plate. **Sales Van** is already ticked from the menu, so
   on save the stock location is created under `<Warehouse>/Vans/<Plate>` and
   assigned. Check the **Van Sales** tab to see it.
2. On the same tab, set the salesman and the cash journal.
3. **Van Sales > Configuration > Routes > New** - leave the code as **New** to
   get `R00001`, assign the van, add customers in visiting order.
4. Press **Plan Today's Visits**. The plan is created *and its stops generated*
   in one step.
5. **Start Day**, then check in and out at each stop. Skipping requires a
   reason; an unplanned stop requires one too.
6. **Close Day**. The plan refuses to close while a stop is still checked in.

## Deliberately absent

* **Visit frequency.** The requirement document asks for "visit days/frequency"
  without defining the pattern, and three incompatible schemes are plausible
  (weekday flags; weekday plus week cycle; frequency code plus anchor date).
  Confirmed with the client that this stays out for now, so plans are created
  explicitly. Frequency is purely additive when it arrives - new columns, no
  migration.
* **Automatic plan generation** (`ir.cron`) follows the frequency model.
* Van stock operations, GRN, reconciliation - `van_sales_stock`.
* Orders, invoices, payments, FOC, returns, credit rules - `van_sales_sale`.
* The mobile synchronisation API - `van_sales_sync`.

## Odoo 19 notes for whoever maintains this

Several Odoo 16/17 idioms fail on 19, silently or loudly. This module avoids
all of them, and any extension should too:

| Old | Odoo 19 |
|---|---|
| `_sql_constraints = [...]` | `models.Constraint(...)` - the old form is **silently ignored** |
| `<tree>` | `<list>` - hard `ValidationError` otherwise |
| `view_mode="tree,form"` | `list,form` - the old value installs fine and breaks at runtime |
| `attrs="{'invisible': [...]}"` | bare Python: `invisible="not field"` - hard error otherwise |
| `<div class="oe_chatter">` | `<chatter/>` - the div renders nothing |
| `res.groups` `category_id` / `users` | `privilege_id` (on `res.groups.privilege`) / `user_ids` |
| `groups_id` on actions and menus | `group_ids` - but `ir.rule` still uses `groups` |
