# Van Sales - Base: Real-World Test Scenario

Module `van_sales_base` `19.0.1.2.0`

A single business, keyed in once, then run as a working day. It exercises both
operating models the client confirmed — fixed rounds to known shops, and free
selling from a van parked at public places — and hits every constraint and
automation on the way.

Use this **instead of** inventing test data. `TESTING.md` is the checklist;
this is the story that produces it. Every step names the case IDs it covers, so
if you work through the day you get most of the checklist for free.

The names below are illustrative. Swap them for the client's own — the shape
matters, not the labels.

---

## The business

**Gulf Fresh Distribution** sells bottled water, juices, laban and packaged
snacks. Three vans go out daily from one warehouse.

Two of them run **fixed rounds**: the salesman knows every shop, most buy on
account, and the office chases the balances. The third is a **mobile shop**: it
parks at labour camps and markets in the evening and sells to whoever walks up,
cash only.

One van does both — it services two grocery shops in an industrial zone in the
morning, then parks at the camp next door.

That mix is the whole reason the route model has two stop kinds.

---

## 1. Master data to key in

### 1.1 Users

| Name | Login | Van Sales role | Notes |
|---|---|---|---|
| Fatima Ali | `van.fatima` | Administrator | Office — sets up vans and routes |
| Suresh Nair | `van.suresh` | Supervisor: All Vans | Sales supervisor |
| Rashid Kamal | `van.rashid` | User: Own Van Only | Drives VAN-01 |
| Anil Kumar | `van.anil` | User: Own Van Only | Drives VAN-02 |
| Joseph Mathew | `van.joseph` | User: Own Van Only | Drives VAN-03, the mobile shop |
| Mohammed Iqbal | `fleet.iqbal` | **none** — give Fleet → Officer only | Control user for the Fleet regression |

### 1.2 Vehicles — create these from **Van Sales → Configuration → Sales Vans**

Fleet requires a model on every vehicle. Create brand `Toyota` with model
`Hiace`, and brand `Isuzu` with model `NPR`, first.

| Plate | Model | Salesman | Cash journal | Purpose |
|---|---|---|---|---|
| `GF-1234` | Hiace | Rashid Kamal | Cash | North round + industrial zone |
| `GF-5678` | Hiace | Anil Kumar | Cash | South round |
| `GF-9012` | NPR | Joseph Mathew | Cash | Mobile shop, evenings |

**Expect on save:** Sales Van already ticked, Loading Warehouse prefilled, and
`WH/Vans/GF-1234` created and assigned with no warning banner.
*(covers VAN-01, VAN-02, VAN-03, VAN-12)*

### 1.3 Customers — Contacts, marked as customers

| Shop | City / Area |
|---|---|
| Al Noor Grocery | Al Qusais |
| Green Mart Supermarket | Al Qusais |
| City Star Cold Store | Muhaisnah |
| Family Fresh Market | Muhaisnah |
| Sunrise Cafeteria | Al Nahda |
| Golden Spoon Restaurant | Al Nahda |
| Daily Needs Baqala | Al Twar |
| Corner Stop Cold Store | Al Twar |
| Al Wasl Mini Mart | Industrial Area |
| Rapid Cool Store | Industrial Area |

### 1.4 Stop locations — **Van Sales → Configuration → Stop Locations**

| Code | Name | City |
|---|---|---|
| `LC-03` | Industrial Area Labour Camp 3 | Industrial Area |
| `FM-01` | Friday Market — North Gate | Al Qusais |
| `BRJ` | Beach Road Junction | Al Nahda |
| `SC-02` | Sports City Gate 2 | Muhaisnah |

*(covers STOP-01, STOP-02)*

### 1.5 Routes — **Van Sales → Configuration → Routes**

Leave the code as **New** every time and let the sequence assign it.

| Expected code | Name | Route Type | Van | Stops, in order |
|---|---|---|---|---|
| `R00001` | North Round | Customer Route | GF-1234 | Al Noor Grocery → Green Mart → City Star → Family Fresh |
| `R00002` | South Round | Customer Route | GF-5678 | Sunrise Cafeteria → Golden Spoon → Daily Needs → Corner Stop |
| `R00003` | Evening Mobile Round | Location Route | GF-9012 | Friday Market → Labour Camp 3 → Beach Road Junction |
| `R00004` | Industrial Zone Round | Customer Route | GF-1234 | Al Wasl Mini Mart → Rapid Cool Store → **Labour Camp 3** *(switch this line's Stop Type to Location)* |

`R00004` is the mixed one, and it is deliberately on the same van as `R00001` —
one van, two routes.
*(covers RTE-01, RTE-02, RTE-07, RTE-08a, RTE-08c, RTE-08d, RTE-14)*

---

## 2. Tuesday — a working day

### Morning, 06:30 — the office (log in as **Fatima**)

**Step 1.** Open `R00001` → **Plan Today's Visits**.

> Plan `R00001 / <today>` opens in Draft with four customer stops already
> listed, in route order. You pressed one button and the stop list built
> itself.
> *(PLAN-01)*

**Step 2.** Do the same for `R00003` (Joseph's mobile round).

> Three **location** stops — Friday Market, Labour Camp 3, Beach Road Junction.
> No customer names anywhere.
> *(PLAN-04a)*

**Step 3.** Press **Plan Today's Visits** on `R00001` again by mistake.

> The same plan opens. No duplicate, no doubled stops.
> *(PLAN-02)*

**Step 4.** Anil is on leave. Create tomorrow's plan for `R00002` from
**Operations → Visit Plans → New**, route `R00002`, date tomorrow.

> Stops generate on save, without pressing anything.
> *(PLAN-03)*

---

### Morning, 07:15 — Rashid starts the north round (log in as **Rashid**)

**Step 5.** Open Van Sales. Note what you can and cannot see.

> Operations only — no Configuration menu. Visit Plans shows *his* plan and
> nothing of Anil's or Joseph's.
> *(SEC-01, SEC-02)*

**Step 6.** Open today's plan and press **Check In** on Al Noor Grocery.
Do *not* press Start Day first.

> The stop goes to Checked In with a timestamp, **and the plan moves itself to
> In Progress**. Look at the plan's chatter — the automatic start is logged
> there, not hidden.
> *(VIS-01)*

**Step 7.** Serve the shop, then **Check Out**.

> Stop → Done. Duration in minutes appears.
> *(VIS-02)*

**Step 8.** Green Mart is shut for a delivery. Press **Skip** with the reason
field empty.

> Blocked: *"Give a reason before skipping…"*. Type `Shop closed - stock
> delivery in progress` and skip again. Row greys out.
> *(VIS-05, VIS-06)*

**Step 9.** City Star and Family Fresh: check in and out normally.

**Step 10.** Al Wasl Mini Mart phones — they are out of laban and want a drop
today, off-plan. On the plan press **Add a line**, pick Stop Type **Customer**,
choose Al Wasl Mini Mart, tick **Unplanned Visit**, leave the reason blank,
save.

> Blocked: *"An unplanned visit needs a reason…"*. Enter `Customer called -
> urgent laban order`, save, then check in and out.
> *(VIS-08, VIS-09, SEC-05)*

**Step 11.** Try **Close Day** while still checked in somewhere.

> Blocked, and it names the stop you are still standing at.
> *(PLAN-10)*

**Step 12.** Check out, then **Close Day**.

> Plan → Done.
> *(PLAN-11)*

**Step 13.** Try to check in on any stop of that closed plan.

> Blocked: *"Plan … is done, so its stops cannot be visited."*
> *(VIS-10)*

---

### Evening, 16:00 — Joseph takes the mobile shop out (log in as **Joseph**)

**Step 14.** Open today's plan. **Check In** at Friday Market.

> A location stop behaves exactly like a customer stop — check in, GPS fields
> stay empty in the backend (the mobile app will fill them), duration computes
> on check-out.
> *(VIS-08c)*

**Step 15.** Busy evening. Check out after a long stay.

> Duration reflects the real gap between the two timestamps.

**Step 16.** Labour Camp 3: check in, sell, check out.

**Step 17.** Driving to Beach Road Junction, Joseph passes a construction site
with a crowd of workers and decides to stop. On the plan **Add a line**, Stop
Type **Location**, and in the Stop Location field type
`Marina Site Gate — Temporary` and use **Create**. Tick Unplanned Visit, reason
`Passing crowd - opportunistic stop`. Save, check in, check out.

> This is the client's "the salesman can also create the stop" case. The new
> place becomes a reusable master record — next month the office can see how
> much was sold there.
> *(VIS-08a, STOP-01)*

**Step 18.** It starts raining. Skip Beach Road Junction with the reason
`Heavy rain - no footfall`.

**Step 19.** **Close Day**.

---

### Evening, 19:00 — Suresh reviews (log in as **Suresh**)

**Step 20.** Open Van Sales → Operations → Visits. Clear the *My Visits*
filter.

> A supervisor sees **all** three salesmen's stops.
> *(SEC-06)*

**Step 21.** Group by **Stop Type**, then by **Salesman**, then by **Stop
Location**.

> Customer stops and location stops separate cleanly. This is the reporting
> the two-model split buys you.
> *(VIS-14)*

**Step 22.** Check the **Duration** column total per salesman.

> Sums per group.
> *(VIS-13)*

**Step 23.** Rashid mis-clicked and checked out of City Star two minutes after
arriving. Open that stop and press **Reset to Planned**.

> Timestamps clear. Confirm Rashid does **not** see this button.
> *(VIS-11, VIS-12)*

**Step 24.** Try to open Configuration.

> Not visible to a supervisor. **Flag this if the client wants supervisors to
> edit routes** — it is a design call, not a defect.
> *(SEC-07)*

---

## 3. Things that go wrong — run these too

These are the situations that actually happen in a distribution business, and
each one lands on a constraint.

**Scenario A — a salesman resigns.**
Anil leaves. Fatima tries to put Rashid on GF-5678 as well, so he can cover
both rounds.

> Blocked: *"Rashid Kamal is already assigned to van GF-1234. A salesman can
> operate only one van at a time…"*
> Now archive GF-1234 and try again — **allowed**, because the constraint only
> counts active vans.
> *(VANC-01, VANC-03)*

**Scenario B — a new van joins the fleet.**
Fatima registers `GF-3456`, an Isuzu NPR, with no plate on the registration
paperwork yet. She leaves the plate blank and saves.

> Location created as `Van <id>`. Two days later the plate arrives; she types
> `GF-3456` and saves.
> The location renames itself to `GF-3456` and the chatter records it.
> *(VAN-04, VAN-05)*

**Scenario C — someone renamed a location by hand.**
The warehouse team renamed `WH/Vans/GF-9012` to `Mobile Shop Stock`. Later the
van's plate is corrected.

> The location is **not** renamed. Only names this module generated are ever
> touched.
> *(VAN-06)*

**Scenario D — a van goes in for service.**
GF-1234 is off the road. Fatima reassigns route `R00001` to GF-5678.

> The route's Salesman changes by itself — it follows the van.
> *(RTE-05)*

**Scenario E — a new shop opens mid-round.**
A new grocery opens on the north round. Fatima adds it to `R00001` at 10:00,
while Rashid's plan is already In Progress. She opens today's plan and presses
**Generate Stops**.

> Only the new shop is added. The four existing stops — one already done, one
> skipped — are untouched.
> *(PLAN-06)*

**Scenario F — the wrong van is set up.**
Fatima ticks Sales Van on the office car by mistake, then unticks it.

> A stock location was created on the first save and **stays** after unticking.
> This is deliberate — the location may already hold stock — but say if you
> want a warning here.
> *(VAN-08)*

**Scenario G — accounting asks who owns which stock.**
Open Inventory → Configuration → Locations.

> `WH/Vans` is a **View** location with one **Internal** child per van. One
> parent, not one per van. Each van's stock is separable and valued.
> *(VAN-02, VAN-03)*

**Scenario H — a Fleet user who has nothing to do with van sales.**
Log in as Mohammed Iqbal (Fleet Officer only).

> He sees **every** vehicle, including all three sales vans, exactly as before
> this module was installed. Then give him the Van Sales *User* role as well
> and look again — **report exactly what he can see**, this is the combination
> most at risk.
> *(FLT-01, FLT-02)*

**Scenario I — two shops with the same name.**
A second `Corner Stop Cold Store` opens in another area and is added to
`R00002` twice by mistake.

> Blocked: *"This customer is already on this route."* Same for adding Friday
> Market twice to `R00003`.
> *(RTE-08, RTE-08b)*

---

## 4. What this scenario does not cover

Not because it is missing, but because it is not built yet:

- Loading stock into the van, GRN, unloading, end-of-day reconciliation
- Selling anything, invoicing, taking payment, cash-up
- Credit limits and statements for the shops on the customer routes
- GPS coordinates — the fields exist, the mobile app will fill them
- Automatic daily plan generation on a schedule — waiting on the frequency model

If the scenario feels thin on "selling", that is correct: `van_sales_base` is
masters and the visit cycle. Selling is `van_sales_sale`.

---

## 5. Coverage map

Working through the day above covers these `TESTING.md` cases:

| Section | Covered by the scenario | Still to test separately |
|---|---|---|
| INST | — | INST-01 … 07 |
| VAN | 01, 02, 03, 04, 05, 06, 08, 12 | 07, 09, 10, 11, 13, 14 |
| VANC | 01, 03 | 02, 04, 05, 06 |
| STOP | 01, 02 | 03, 04, 05, 06, 07 |
| RTE | 01, 02, 05, 07, 08, 08a, 08b, 08c, 08d, 14 | 03, 04, 06, 09, 10, 11, 12, 13, 08e |
| PLAN | 01, 02, 03, 04a, 06, 10, 11 | 04, 04b, 05, 07, 08, 09, 12, 13, 14, 15, 16, 17, 18 |
| VIS | 01, 02, 05, 06, 08, 08a, 08c, 09, 10, 11, 12, 13, 14 | 03, 04, 07, 08b, 15, 16 |
| SEC | 01, 02, 05, 06, 07 | 01a, 03, 04, 08, 09, 10 |
| FLT | 01, 02 | 03 … 07 |
| EDGE | — | 01 … 07 |

Run the scenario first — it is faster and it surfaces the problems that matter.
Then sweep the "still to test" column, which is mostly negative cases.

---

## 6. Reporting back

Same format as `TESTING.md`. For anything that fails, tell me the **step
number** as well as the case ID — the step tells me what the business was
trying to do, which is usually more useful than the assertion that broke.

If a step felt wrong *as a business flow* even though nothing errored, that is
the most valuable feedback of all. Say so plainly.
