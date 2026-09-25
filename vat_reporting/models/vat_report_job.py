from odoo import fields, models


class VatReportJob(models.Model):
    _name = 'vat.report.job'
    _description = 'VAT Report Extraction Job'
    _order = 'create_date desc'

    report_id = fields.Many2one('vat.report', required=True, ondelete='cascade')
    attachment_id = fields.Many2one('ir.attachment', string='File')
    filename = fields.Char()
    job_id = fields.Char(string='Job ID')
    status = fields.Selection([
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ], default='queued', string='Status')
    progress = fields.Integer(string='Progress (%)')
    error_message = fields.Text(string='Error')
    results_fetched = fields.Boolean(default=False)
