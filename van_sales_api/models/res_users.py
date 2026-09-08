# Part of the Van Sales project.

from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    van_sales_device_ids = fields.One2many(
        'van.sales.device', 'user_id', string="Van Sales Devices")
    van_sales_lang = fields.Selection(
        selection=[('en_US', "English"), ('ar_001', "Arabic")],
        string="Mobile Language", default='en_US',
        help="Language the van sales app shows to this salesman.")
