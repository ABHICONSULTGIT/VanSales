from odoo import api, fields, models


class VatReportConfig(models.TransientModel):
    _name = 'vat.report.config'
    _description = 'VAT Reporting API Settings'

    api_base_url = fields.Char(string='API Base URL', required=True)
    api_token = fields.Char(string='API Bearer Token', required=True)

    def _get_param(self, key, default):
        return self.env['ir.config_parameter'].sudo().get_param(key, default)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        res['api_base_url'] = self._get_param('vat_reporting.api_base_url', 'http://20.244.85.207:9005')
        res['api_token'] = self._get_param('vat_reporting.api_token', 'VINNO-CA-11')
        return res

    def action_save(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('vat_reporting.api_base_url', self.api_base_url)
        ICP.set_param('vat_reporting.api_token', self.api_token)
        return {'type': 'ir.actions.act_window_close'}
