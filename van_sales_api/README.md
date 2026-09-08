# Van Sales - Mobile API (`van_sales_api`)

Fourth module of the Van Sales suite. **Odoo 19 Enterprise**, version
`19.0.1.0.0`. Depends on `van_sales_sale`.

Follows the Red Ladder mobile API architecture — `/api/v1/` routes, hashed
bearer tokens, one JSON envelope, a full request/response log, Firebase push —
**plus the offline sync layer that van sales needs and Red Ladder never did**.

Postman collection: `Van_Sales_Mobile_API_v1.postman_collection.json` at the
repository root, alongside the Red Ladder ones. 30 requests, 6 folders, and
every URL in it was verified against the declared routes.

---

## Endpoints

19 routes. Every one is `type='http'`, `auth='public'` (the decorator owns
authentication), accepts `OPTIONS`, and sets `csrf=False`, `cors='*'`.

| Method | Path | Guard |
|---|---|---|
| POST | `/api/v1/auth/login` | public, rate limited |
| POST | `/api/v1/auth/refresh` | token |
| POST | `/api/v1/auth/logout` | token |
| GET | `/api/v1/auth/me` | token |
| POST | `/api/v1/auth/change-password` | token |
| POST | `/api/v1/device/register` | token |
| POST | `/api/v1/device/heartbeat` | token |
| POST/PUT | `/api/v1/device/fcm-token` | token |
| POST/GET | `/api/v1/sync/bootstrap` | token + device |
| POST | `/api/v1/sync/pull` | token + device |
| POST | `/api/v1/sync/filter-local` | token + device |
| POST | `/api/v1/sync/push` | token + device |
| GET | `/api/v1/lookup/customers` | token |
| GET | `/api/v1/lookup/products` | token |
| GET | `/api/v1/lookup/van-stock` | token + device |
| GET | `/api/v1/lookup/open-invoices` | token |
| GET | `/api/v1/notifications` | token |
| GET | `/api/v1/notifications/unread-count` | token |
| POST | `/api/v1/notifications/read` | token |

Response envelope, identical on success and failure:

```json
{ "success": true, "message": "…", "data": { }, "error": null }
```

plus `pagination` on lists and `code` on errors. Every serialised field passes
through `_s` / `_i` / `_f` / `_b` / `_l`, so the app never receives Odoo's
`False`.

---

## The two things the mobile team must get right

### 1. The watermark belongs to the client

Every pull response carries `server_time`. Store it, send it back as `since` on
the next pull.

It is the **transaction start time**, not wall clock — using `now()` would skip
a record written a millisecond after the query but before the reply.

The server records the watermark on the device too, but **only as a
diagnostic**. If the server advanced it on its own and the app then failed to
apply the response, the records in between would never be sent again. The
client is the source of truth.

### 2. Idempotency is not optional

Every pushed record carries a `client_uuid` the app generates **before the
record exists**. `van.sales.sync.log` stores it with a database-level unique
constraint.

A van loses signal constantly, so the app *will* re-send batches whose reply it
never arrived. Re-sending is safe: the server answers `duplicate` with the
original id rather than creating a second order. **Request 4.9 in the Postman
collection proves exactly this** — it re-sends 4.5 with the same UUID and
asserts the same order id comes back.

Records are processed **one savepoint each**. One rejection never discards the
rest of the batch, because the device cannot tell the good from the bad and
would re-send everything. Request 4.10 demonstrates it with a deliberately
mixed batch.

### Offline document numbering

`POST /device/register` returns a **`device_number`**, issued once from a
`no_gap` sequence and never re-issued — re-registering the same handset
refreshes its details but keeps the number, because references the app has
already generated depend on it.

The app prefixes its offline references with it, so two handsets both out of
signal cannot produce the same reference. Same mechanism as Odoo's own Point of
Sale (`pos.config.register_new_device_identifier`).

---

## What syncs

23 models, in a fixed order so each can filter on what came before — route
lines on their routes, invoices on the customers actually being sent.

**Masters:** company, user, van, routes and their stops, stop locations,
customers, units, products, categories, taxes, pricelists and items, van stock.

**Documents:** visit plans, visits, open invoices, orders and lines,
collections and lines, van transfers and moves.

Scoped twice over: to the device's **own van**, and to a recent window
(`van_sales.sync_history_days`, default 7). A van with 40 shops does not
download 12,000 contacts, and nobody needs last year's visits on a handset.

**Pushable:** `van.sales.visit` (check in / out / skip / unplanned),
`sale.order` (create, confirm, deliver, invoice in one call),
`van.sales.collection`, `stock.picking` (van load confirmation).

Rejections carry a stable code — `STOCK_INSUFFICIENT`,
`CREDIT_LIMIT_EXCEEDED`, `INVOICE_ALREADY_PAID`, `VALIDATION_ERROR` — because
§6.2 asks for errors that "map cleanly to user-facing app messages", and a
translated sentence cannot be matched on.

---

## Configuration

| System parameter | Default | Purpose |
|---|---|---|
| `van_sales.api_log_enabled` | `True` | Master switch for request logging |
| `van_sales.api_log_retention_days` | `30` | Daily cleanup cron |
| `van_sales.api_token_expiry_days` | `30` | Token lifetime |
| `van_sales.sync_product_limit` | `5000` | Products per sync |
| `van_sales.sync_partner_limit` | `2000` | Customers per sync |
| `van_sales.sync_history_days` | `7` | How far back documents are sent |
| `van_sales.fcm_service_account_json` | *(empty)* | Firebase service account JSON |
| `van_sales.fcm_android_channel_id` | *(empty)* | Android notification channel |

The FCM parameter is **van-sales specific**, so this can point at its own
Firebase project or share another one — a configuration choice, not a code
change.

**Backend screens:** Van Sales → Mobile → Devices, Push Notifications, Sync
Log, API Log.

---

## Three deviations from the Red Ladder pattern, each on purpose

1. **`firebase_admin` is not a hard external dependency.** Odoo refuses to load
   a module whose external dependency is missing, and the API — the point of
   this module — must not be blocked by an optional push library. The import is
   guarded instead and push degrades with a log line. `pip install
   firebase-admin` to enable it.
2. **`models.Constraint`, never `_sql_constraints`.** Odoo 19 silently ignores
   the old form — see the note below.
3. **The request timer lives on the request**, not in a module-level dict keyed
   by `id(request)`. Any request that returns without passing through the
   envelope would leave an entry in such a dict, and it grows for the life of
   the worker.

And one addition: **`X-Device-ID` is mandatory and meaningful.** In Red Ladder
it is an optional hint for merging a guest cart. Here the device is a
first-class record carrying the numbering sequence and the watermark, so every
sync call must name it — `@device_required` enforces it, and a deactivated
device is cut off from its very next call.

## A finding in the Red Ladder module

While studying it: **`_sql_constraints` is silently ignored in Odoo 19**
(`odoo/orm/model_classes.py` logs a warning and creates nothing). It is used in
`red_ladder_mobile_api/models/api_access_token.py`, `fcm_device.py` and
`guest_cart.py` — so **token uniqueness and FCM token uniqueness do not exist
in that database**. Duplicate tokens are possible. Worth its own ticket; the
fix is a one-line change per model.

Two smaller ones there: the login rate limiter is per worker (four workers means
four times the ceiling), and `_request_start_time` leaks an entry for any
request that does not reach the envelope.

---

## What the API deliberately does not cover

The endpoints stop where the Odoo modules stop. There is nothing for
**free-of-charge lines, returns and credit notes, end-of-day cash hand-in, or
approvals**, because those features do not exist yet — they are blocked on
client decisions.

That is the right order. Each of them adds fields the sync layer must carry, so
building endpoints for them now would mean rewriting them as each answer lands.
**Auth, device and pull are stable and the mobile team can build against them
today**; the push contract will grow as the held features arrive.

---

## Running the collection

1. Install `van_sales_api`, then run both demo-data scripts so there is a van,
   a route, products and stock.
2. Import `Van_Sales_Mobile_API_v1.postman_collection.json`.
3. Check `base_url` — it defaults to `http://localhost:8019`, matching
   `odoo.conf`.
4. Run the folders in order: **1 Auth → 2 Device → 3 Sync Pull → 4 Sync Push**.
   Login seeds fresh UUIDs and every later request reads ids the earlier ones
   stored, so the collection runs top to bottom with nothing copied by hand.

The two requests worth watching: **4.9** proves a re-sent order does not
duplicate, and **4.10** proves one bad record does not discard a batch.
