# VAT Reporting — Custom Odoo 19 Module

## What it does
- Adds a **VAT Reporting** app icon to the Odoo home screen.
- Opening it shows a list with a **New** button.
- The form has: Company, Quarter, an auto-generated Reference Number
  (`<QUARTER>-<YEAR>-0001`, e.g. `Q1-2025-0001`), and a multi-file upload
  widget for the bills (PDF/JPG/PNG).
- **Upload & Extract** sends every uploaded bill to the extraction API
  (`/extract`), creates a job per file, and immediately does a first
  `/job-status` check. If a job has finished, `/job-results` is fetched
  automatically and the invoice lines table is filled in:
  Date, Invoice Number, Supplier, Supplier VAT, Total Amount, VAT Amount,
  Total Incl. VAT.
- If a job is still processing, click **Refresh Job Status** later to
  check again and pull the results in.
- An "Extraction Jobs" tab shows the status/progress/error of every job,
  for troubleshooting.

## Installation
1. Copy the `vat_reporting` folder into your custom addons path, e.g.:
   `/opt/odoo18/custom_addons/vat_reporting` (use whatever path is in
   your `addons_path`, even on an Odoo 19 install).
2. Restart the Odoo service.
3. In Odoo: enable developer mode → Apps → **Update Apps List** →
   search "VAT Reporting" → Install.

## API configuration
Defaults are pre-loaded from the API document you provided:
- Base URL: `http://20.244.85.207:9005`
- Bearer Token: `VINNO-CA-11`

To change these later without touching code, go to:
**VAT Reporting → Configuration → API Settings**

These are stored as `ir.config_parameter` records:
- `vat_reporting.api_base_url`
- `vat_reporting.api_token`

> Make sure the Odoo server itself (not just your browser) has outbound
> network access to that host/port — the requests are made server-side.

## About the result field mapping
The API document only specifies that `/job-results` returns a `results`
list "in the client's original data structure" — it doesn't fix exact
key names. The module therefore tries several common key-name variants
for each column (see `models/vat_report_line.py`, the `*_KEYS` lists at
the top of the file). The full raw JSON for each line is also kept in a
hidden `raw_data` field for troubleshooting.

The sample invoice file you mentioned (`RUKHBANA_COLDSTORE...`) didn't
actually come through in the upload, so this mapping is based on common
invoice field names rather than your real API output. Once you run a
real extraction, if a column comes back empty, send me the raw JSON from
that line (or the `/job-results` response) and I'll tighten the mapping.

## Notes / possible follow-ups
- `supplier` is a plain text field (not linked to `res.partner`) since
  OCR output won't reliably match existing contacts. Happy to add
  partner-matching logic later if useful.
- The invoice lines table is editable, so any extraction mistakes can be
  corrected by hand before you rely on the totals.
- Reference numbering is scoped per company + quarter + year and resets
  to `0001` for each new quarter/year combination.
