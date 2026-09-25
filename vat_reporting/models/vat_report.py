import base64
import io
import logging
import time

import requests
try:
    from PyPDF2 import PdfReader, PdfWriter
    _HAS_PYPDF2 = True
except ImportError:
    _HAS_PYPDF2 = False

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

QUARTER_SELECTION = [
    ('Q1', 'Q1 (Jan - Mar)'),
    ('Q2', 'Q2 (Apr - Jun)'),
    ('Q3', 'Q3 (Jul - Sep)'),
    ('Q4', 'Q4 (Oct - Dec)'),
]

# Maximum minutes a job is allowed to stay in processing before being marked failed.
# 26MB / 59-page fully-scanned PDFs can take 45+ minutes to OCR on the server.
JOB_TIMEOUT_MINUTES = 90


class VatReport(models.Model):
    _name = 'vat.report'
    _description = 'VAT Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'reference'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company, tracking=True)
    quarter = fields.Selection(
        QUARTER_SELECTION, string='Quarter', required=True, tracking=True)
    year = fields.Integer(
        string='Year', required=True,
        default=lambda self: fields.Date.context_today(self).year, tracking=True)
    invoice_type = fields.Selection([
        ('sales_invoice', 'Sales Invoice'),
        ('sales_return', 'Sales Return'),
        ('purchase_invoice', 'Purchase Invoice'),
        ('purchase_return', 'Purchase Return'),
    ], string='Invoice Type', default='purchase_invoice', required=True, tracking=True)
    reference = fields.Char(
        string='Reference Number', readonly=True, copy=False, index=True)

    attachment_ids = fields.Many2many(
        'ir.attachment', 'vat_report_attachment_rel', 'report_id', 'attachment_id',
        string='Upload Bills',
        help='Upload one or more bills (PDF, JPG or PNG). Click "Upload & Extract" '
             'to send them to the extraction API.')

    job_ids  = fields.One2many('vat.report.job', 'report_id', string='Extraction Jobs')
    line_ids = fields.One2many('vat.report.line', 'report_id', string='Invoice Lines')
    
    sales_line_ids = fields.One2many(
        'vat.report.line', 'report_id', string='Sales Lines',
        domain=[('invoice_type', 'in', ('sales_invoice', 'sales_return'))]
    )
    purchase_line_ids = fields.One2many(
        'vat.report.line', 'report_id', string='Purchase Lines',
        domain=[('invoice_type', 'in', ('purchase_invoice', 'purchase_return'))]
    )

    state = fields.Selection([
        ('draft',      'Draft'),
        ('processing', 'Processing'),
        ('done',       'Done'),
    ], default='draft', tracking=True, string='Status')

    pending_job_count = fields.Integer(compute='_compute_job_counts')
    failed_job_count  = fields.Integer(compute='_compute_job_counts')
    job_count         = fields.Integer(compute='_compute_job_counts')

    currency_id       = fields.Many2one(related='company_id.currency_id', readonly=True)
    total_amount      = fields.Monetary(compute='_compute_totals', string='Total (Excl. VAT)', store=True)
    total_vat_amount  = fields.Monetary(compute='_compute_totals', string='Total VAT', store=True)
    total_amount_incl = fields.Monetary(compute='_compute_totals', string='Total (Incl. VAT)', store=True)

    _sql_constraints = [
        ('reference_company_uniq', 'unique(reference, company_id)',
         'The reference number must be unique per company!'),
    ]

    # ── Search/filter fields (stored so they persist after clicking Search) ──
    line_search_date     = fields.Date(string='Date')
    line_search_invoice  = fields.Char(string='Invoice No.')
    line_search_supplier = fields.Char(string='Supplier')

    # ── Computed filtered lines (displayed when a filter is active) ───────
    sales_line_ids = fields.One2many(
        'vat.report.line', 'report_id', string='Sales Lines',
        domain=[('invoice_type', 'in', ('sales_invoice', 'sales_return'))]
    )
    purchase_line_ids = fields.One2many(
        'vat.report.line', 'report_id', string='Purchase Lines',
        domain=[('invoice_type', 'in', ('purchase_invoice', 'purchase_return'))]
    )
    correction_line_ids = fields.One2many(
        'vat.report.line', 'report_id', string='Correction Lines',
        domain=[('parse_warning', '=', True)]
    )

    def action_apply_search(self):
        """Save search terms and reload form so one2many domain re-filters."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'vat.report',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_clear_search(self):
        """Clear all line search filters and reload."""
        self.write({
            'line_search_date': False,
            'line_search_invoice': False,
            'line_search_supplier': False,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'vat.report',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }


    @api.depends('line_ids.total_amount', 'line_ids.vat_amount', 'line_ids.total_including_vat')
    def _compute_totals(self):
        for rec in self:
            rec.total_amount      = sum(rec.line_ids.mapped('total_amount'))
            rec.total_vat_amount  = sum(rec.line_ids.mapped('vat_amount'))
            rec.total_amount_incl = sum(rec.line_ids.mapped('total_including_vat'))

    @api.depends('job_ids.status')
    def _compute_job_counts(self):
        for rec in self:
            rec.job_count         = len(rec.job_ids)
            rec.pending_job_count = len(rec.job_ids.filtered(
                lambda j: j.status in ('queued', 'processing')))
            rec.failed_job_count  = len(rec.job_ids.filtered(
                lambda j: j.status == 'failed'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('reference'):
                vals['reference'] = self._generate_reference(vals)
        return super().create(vals_list)

    def _generate_reference(self, vals):
        quarter    = vals.get('quarter')
        if not quarter:
            return False
        company_id = vals.get('company_id') or self.env.company.id
        year       = vals.get('year') or fields.Date.context_today(self).year
        domain     = [('company_id', '=', company_id), ('quarter', '=', quarter), ('year', '=', year)]
        count      = self.search_count(domain)
        return f"{quarter}-{year}-{count + 1:04d}"

    def _get_api_base_url(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'vat_reporting.api_base_url', 'http://20.244.85.207:9005').rstrip('/')

    def _get_api_headers(self):
        token = self.env['ir.config_parameter'].sudo().get_param(
            'vat_reporting.api_token', 'VINNO-CA-11')
        return {'Authorization': f'Bearer {token}'}

    # ── Button actions ────────────────────────────────────────────────

    def action_extract_invoices(self):
        self.ensure_one()
        if not self.attachment_ids:
            raise UserError(_('Please upload at least one bill (PDF, JPG or PNG) first.'))

        base_url     = self._get_api_base_url()
        headers      = self._get_api_headers()
        active_jobs  = self.job_ids.filtered(lambda j: j.status != 'failed')
        already_sent = active_jobs.mapped('attachment_id')
        to_send      = self.attachment_ids - already_sent

        if not to_send:
            raise UserError(_('All uploaded bills have already been sent for extraction. '
                               'Use "Refresh Job Status" to check on them, or upload a new bill.'))

        server_down = False  # circuit breaker: True once we know the API is unreachable
        for attachment in to_send:
            pages = self._split_pdf_pages(attachment)
            if pages:
                # Multi-page PDF — upload each page as a separate job
                _logger.info('VAT Reporting: splitting "%s" into %d pages for extraction',
                             attachment.name, len(pages))
                for page_num, (page_name, page_bytes) in enumerate(pages, start=1):
                    if server_down:
                        # API is unreachable — fail remaining pages immediately
                        self.env['vat.report.job'].create({
                            'report_id':     self.id,
                            'attachment_id': attachment.id,
                            'filename':      page_name,
                            'status':        'failed',
                            'error_message': _('Skipped: API server was unreachable for earlier pages.'),
                        })
                        continue
                    failed_with_conn_err = self._send_file_for_extraction(
                        attachment, page_name, page_bytes, 'application/pdf',
                        base_url, headers)
                    if failed_with_conn_err:
                        server_down = True
                    time.sleep(0.2)
            else:
                # Single-page PDF or image — send as-is
                if server_down:
                    self.env['vat.report.job'].create({
                        'report_id':     self.id,
                        'attachment_id': attachment.id,
                        'filename':      attachment.name,
                        'status':        'failed',
                        'error_message': _('Skipped: API server was unreachable for earlier files.'),
                    })
                else:
                    file_content = base64.b64decode(attachment.datas or b'')
                    failed_with_conn_err = self._send_file_for_extraction(
                        attachment, attachment.name, file_content,
                        attachment.mimetype or 'application/octet-stream',
                        base_url, headers)
                    if failed_with_conn_err:
                        server_down = True

        self.state = 'processing'
        self._refresh_jobs(self.job_ids.filtered(lambda j: j.status in ('queued', 'processing')))
        return True

    def _split_pdf_pages(self, attachment):
        """
        If attachment is a multi-page PDF, return a list of (name, bytes) tuples,
        one per page.  Returns [] for single-page PDFs or non-PDF files.
        """
        if not _HAS_PYPDF2:
            return []
        mime = (attachment.mimetype or '').lower()
        name = attachment.name or ''
        if 'pdf' not in mime and not name.lower().endswith('.pdf'):
            return []  # Not a PDF

        try:
            raw = base64.b64decode(attachment.datas or b'')
            reader = PdfReader(io.BytesIO(raw))
            num_pages = len(reader.pages)
        except Exception as exc:
            _logger.warning('VAT Reporting: could not read PDF "%s": %s', name, exc)
            return []

        if num_pages <= 1:
            return []  # Single page — no split needed

        stem = name[:-4] if name.lower().endswith('.pdf') else name
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            writer = PdfWriter()
            writer.add_page(page)
            buf = io.BytesIO()
            writer.write(buf)
            page_bytes = buf.getvalue()
            page_name  = f'{stem}_page{i:03d}.pdf'
            pages.append((page_name, page_bytes))
        return pages

    def action_retry_failed_jobs(self):
        self.ensure_one()
        failed_jobs = self.job_ids.filtered(lambda j: j.status == 'failed')
        if not failed_jobs:
            raise UserError(_('There are no failed extraction jobs to retry.'))

        base_url           = self._get_api_base_url()
        headers            = self._get_api_headers()
        failed_attachments = failed_jobs.mapped('attachment_id')
        failed_jobs.unlink()

        server_down = False  # circuit breaker
        for attachment in failed_attachments:
            pages = self._split_pdf_pages(attachment)
            if pages:
                for page_name, page_bytes in pages:
                    if server_down:
                        self.env['vat.report.job'].create({
                            'report_id':     self.id,
                            'attachment_id': attachment.id,
                            'filename':      page_name,
                            'status':        'failed',
                            'error_message': _('Skipped: API server was unreachable for earlier pages.'),
                        })
                        continue
                    failed_with_conn_err = self._send_file_for_extraction(
                        attachment, page_name, page_bytes, 'application/pdf',
                        base_url, headers)
                    if failed_with_conn_err:
                        server_down = True
                    time.sleep(0.2)
            else:
                if server_down:
                    self.env['vat.report.job'].create({
                        'report_id':     self.id,
                        'attachment_id': attachment.id,
                        'filename':      attachment.name,
                        'status':        'failed',
                        'error_message': _('Skipped: API server was unreachable for earlier files.'),
                    })
                else:
                    file_content = base64.b64decode(attachment.datas or b'')
                    failed_with_conn_err = self._send_file_for_extraction(
                        attachment, attachment.name, file_content,
                        attachment.mimetype or 'application/octet-stream',
                        base_url, headers)
                    if failed_with_conn_err:
                        server_down = True

        if self.state == 'done':
            self.state = 'processing'
        self._refresh_jobs(self.job_ids.filtered(lambda j: j.status in ('queued', 'processing')))
        return True

    def _send_file_for_extraction(self, attachment, filename, file_bytes, mimetype,
                                  base_url, headers):
        """Send raw bytes (may be one page of a split PDF) to the /extract endpoint.

        Returns True if the failure was a connection error (server unreachable),
        so callers can implement a circuit breaker and skip remaining pages.
        Returns False (or None) on success or non-connection errors.
        """
        job_vals = {
            'report_id':     self.id,
            'attachment_id': attachment.id,
            'filename':      filename,
        }
        # Split timeout: 30s to establish connection, 600s to receive response.
        # This prevents hanging for 10 minutes per attempt when the server is down.
        _TIMEOUT = (30, 600)
        attempts = 3
        connection_error = False  # True if failure was definitely "server unreachable"
        for attempt in range(attempts):
            try:
                files    = {'file': (filename, file_bytes, mimetype)}
                data     = {'doc_type': 'invoice'}
                response = requests.post(f'{base_url}/extract', headers=headers,
                                         data=data, files=files, timeout=_TIMEOUT)
                response.raise_for_status()
                result = response.json()
                job_vals.update({
                    'job_id': result.get('job_id'),
                    'status': result.get('status') or 'queued',
                    'error_message': False,
                })
                self.env['vat.report.job'].create(job_vals)
                return False  # success
            except requests.exceptions.ConnectionError as exc:
                # Server is definitively unreachable (connection refused / DNS failure).
                # No point retrying — fail immediately and signal the caller.
                _logger.warning(
                    'VAT Reporting: API server unreachable for %s (no retry): %s', filename, exc)
                job_vals.update({'status': 'failed', 'error_message': str(exc)})
                connection_error = True
                break
            except requests.exceptions.RequestException as exc:
                if attempt == attempts - 1:
                    _logger.warning('VAT Reporting: upload failed for %s: %s', filename, exc)
                    job_vals.update({'status': 'failed', 'error_message': str(exc)})
                else:
                    _logger.info('VAT Reporting: retrying upload for %s (attempt %d/%d) due to: %s',
                                 filename, attempt + 1, attempts, exc)
                    time.sleep(1.0)
            except ValueError as exc:
                if attempt == attempts - 1:
                    _logger.warning('VAT Reporting: invalid JSON for %s: %s', filename, exc)
                    job_vals.update({'status': 'failed',
                                     'error_message': _('Invalid response from API: %s') % exc})
                else:
                    _logger.info('VAT Reporting: retrying upload for %s (attempt %d/%d) due to: %s',
                                 filename, attempt + 1, attempts, exc)
                    time.sleep(1.0)
        self.env['vat.report.job'].create(job_vals)
        return connection_error

    def _send_attachment_for_extraction(self, attachment, base_url, headers):
        """Legacy helper — sends the full attachment without splitting."""
        file_content = base64.b64decode(attachment.datas or b'')
        self._send_file_for_extraction(
            attachment, attachment.name, file_content,
            attachment.mimetype or 'application/octet-stream',
            base_url, headers)

    def action_refresh_jobs(self):
        self.ensure_one()
        base_url = self._get_api_base_url()
        headers  = self._get_api_headers()

        # Always re-fetch completed jobs whose results were never fetched
        # (handles both the race condition AND the is_ready bug where results
        #  were permanently marked as fetched before they were actually ready)
        unfetched = self.job_ids.filtered(
            lambda j: j.status == 'completed' and not j.results_fetched and j.job_id)
        if unfetched:
            for job in unfetched:
                self._fetch_job_results(job, headers, base_url)

        pending = self.job_ids.filtered(lambda j: j.status in ('queued', 'processing'))
        if not pending and not unfetched:
            raise UserError(_('There are no pending extraction jobs to refresh.'))
        if pending:
            self._refresh_jobs(pending)
        if self.job_ids and all(j.status == 'completed' for j in self.job_ids):
            self.state = 'done'
        return True

    def action_refetch_all_results(self):
        """
        Force re-fetch results for ALL completed jobs, regardless of results_fetched flag.
        Use this to recover missing invoice lines when the report is already 'Done'
        but some bills (especially the last one) failed to extract.
        """
        self.ensure_one()
        completed = self.job_ids.filtered(
            lambda j: j.status == 'completed' and j.job_id)
        if not completed:
            raise UserError(_('No completed extraction jobs found to re-fetch.'))

        base_url = self._get_api_base_url()
        headers  = self._get_api_headers()

        # Reset results_fetched so _fetch_job_results will process results again
        completed.write({'results_fetched': False})

        for job in completed:
            self._fetch_job_results(job, headers, base_url)

        if self.job_ids and all(j.status == 'completed' for j in self.job_ids):
            self.state = 'done'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Re-fetch Complete'),
                'message': _('Results re-fetched for %d jobs. Check the invoice lines.') % len(completed),
                'type': 'success',
                'sticky': False,
            },
        }

    # ── Scheduled / auto-poll ─────────────────────────────────────────

    @api.model
    def cron_poll_pending_jobs(self):
        """
        Called every minute by the scheduled action.
        1. Fetches results for jobs already completed but not yet fetched
           (handles race where job finishes between upload and first poll).
        2. Polls all still-pending jobs.
        3. Times out jobs stuck for more than JOB_TIMEOUT_MINUTES minutes.
        """
        base_url = self._get_api_base_url()
        headers  = self._get_api_headers()

        # Pass 1: completed but results not yet fetched (race condition fix)
        unfetched_jobs = self.env['vat.report.job'].search([
            ('status', '=', 'completed'),
            ('results_fetched', '=', False),
            ('job_id', '!=', False),
        ])
        if unfetched_jobs:
            _logger.info('VAT Reporting cron: fetching results for %d completed-unfetched jobs',
                         len(unfetched_jobs))
            for job in unfetched_jobs:
                job.report_id._fetch_job_results(job, headers, base_url)
            for report in unfetched_jobs.mapped('report_id'):
                if report.job_ids and all(j.status == 'completed' for j in report.job_ids):
                    report.state = 'done'

        # Pass 2: poll all still-pending jobs
        processing_reports = self.search([('state', '=', 'processing')])
        if not processing_reports:
            return

        _logger.info('VAT Reporting cron: checking %d processing reports', len(processing_reports))

        for report in processing_reports:
            pending_jobs = report.job_ids.filtered(lambda j: j.status in ('queued', 'processing'))

            # Mark timed-out jobs as failed so user can retry
            for job in pending_jobs:
                if job.create_date:
                    age_minutes = (fields.Datetime.now() - job.create_date).total_seconds() / 60
                    if age_minutes > JOB_TIMEOUT_MINUTES:
                        _logger.warning(
                            'VAT Reporting: job %s timed out after %.1f min — marking failed',
                            job.job_id, age_minutes)
                        job.write({
                            'status': 'failed',
                            'error_message': _(
                                'Job timed out after %d minutes with no response from API. '
                                'Please use "Retry Failed Jobs" to re-submit.'
                            ) % JOB_TIMEOUT_MINUTES,
                        })

            still_pending = report.job_ids.filtered(lambda j: j.status in ('queued', 'processing'))
            if still_pending:
                report._refresh_jobs(still_pending)

    # ── Core polling logic ────────────────────────────────────────────

    def _refresh_jobs(self, jobs):
        if not jobs:
            return
        base_url = self._get_api_base_url()
        headers  = self._get_api_headers()

        for job in jobs:
            if not job.job_id:
                continue
            try:
                resp = requests.get(f'{base_url}/job-status', headers=headers,
                                    params={'job_id': job.job_id}, timeout=60)
                resp.raise_for_status()
                status_data = resp.json()
            except (requests.exceptions.RequestException, ValueError) as exc:
                _logger.warning('VAT Reporting: status check failed for %s: %s', job.job_id, exc)
                job.error_message = str(exc)
                continue

            _logger.info('VAT Reporting: job %s status=%s', job.job_id, status_data)

            new_status = status_data.get('status') or job.status
            if new_status in ('done', 'complete', 'finished'):
                new_status = 'completed'

            progress_raw = status_data.get('progress')
            try:
                new_progress = int(float(str(progress_raw).replace('%', '').strip())) \
                    if progress_raw is not None else job.progress
            except (ValueError, TypeError):
                new_progress = job.progress

            job.write({
                'status':        new_status,
                'progress':      new_progress,
                'error_message': status_data.get('error') or False,
            })

            if new_status == 'completed' and not job.results_fetched:
                self._fetch_job_results(job, headers, base_url)

        if self.job_ids and all(j.status == 'completed' for j in self.job_ids):
            self.state = 'done'

    def _fetch_job_results(self, job, headers, base_url):
        try:
            resp = requests.get(f'{base_url}/job-results', headers=headers,
                                params={'job_id': job.job_id}, timeout=60)
            resp.raise_for_status()
            results_data = resp.json()
        except (requests.exceptions.RequestException, ValueError) as exc:
            _logger.warning('VAT Reporting: fetch results failed for %s: %s', job.job_id, exc)
            job.error_message = str(exc)
            return

        _logger.info('VAT Reporting: job %s results=%s', job.job_id, str(results_data)[:5000])

        # ── Normalise the results payload ─────────────────────────────
        # API may return:
        #   {"results": [...], "is_ready": true}   ← actual response format
        #   {"results": [...], "has_results": true} ← documented format
        #   {"results": {…}}                        ← single invoice as dict
        #
        # IMPORTANT: the real API uses "is_ready" NOT "has_results".
        # When is_ready=false the results aren't finished yet — do NOT mark fetched.
        has_results = results_data.get('has_results')
        is_ready    = results_data.get('is_ready')     # actual API field

        # "Not ready" = either flag is explicitly False
        not_ready = (has_results is False) or (is_ready is False)

        results_list = results_data.get('results') or []
        if isinstance(results_list, dict):
            results_list = [results_list]

        if not results_list:
            if not_ready:
                _logger.info(
                    'VAT Reporting: job %s — results not ready yet '
                    '(is_ready=%s has_results=%s). Will retry on next poll. '
                    'Full response: %s',
                    job.job_id, is_ready, has_results, str(results_data)[:1000])
                # Do NOT set results_fetched=True — let the next cron cycle retry
                return
            _logger.warning(
                'VAT Reporting: job %s — empty results '
                '(is_ready=%s has_results=%s). Full response: %s',
                job.job_id, is_ready, has_results, str(results_data)[:3000])
            job.results_fetched = True
            return

        Line    = self.env['vat.report.line']
        created = 0
        skipped = 0
        for entry in results_list:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            if list(entry.keys()) == ['error']:
                _logger.warning('VAT Reporting: job %s entry error: %s',
                                job.job_id, entry.get('error'))
                skipped += 1
                continue
            Line.create_from_api(self.id, job.id, entry)
            created += 1

        _logger.info('VAT Reporting: job %s → created %d lines, skipped %d.',
                     job.job_id, created, skipped)

        # Only mark as permanently fetched when we actually got lines.
        # If all entries were errors/skipped and the API said not_ready,
        # allow a future retry so the last bill isn't permanently lost.
        if created == 0 and skipped > 0 and not_ready:
            _logger.warning(
                'VAT Reporting: job %s — all %d entries were errors/skipped '
                'and API is not yet ready. Will retry.',
                job.job_id, skipped)
            return  # do NOT set results_fetched=True

        job.results_fetched = True