{
    'name': 'VAT Reporting',
    'version': '19.0.1.1.0',
    'category': 'Accounting/Localization',
    'summary': 'Quarterly VAT reporting with automated invoice data extraction via external OCR API',
    'description': """
VAT Reporting
=============

Create quarterly VAT reports, upload supplier bills (PDF / JPG / PNG) and let
the configured extraction API read the invoice data for you.

Features
--------
* Dedicated home screen app ("VAT Reporting") with a "New" button.
* Form with Company, Quarter, auto-generated Reference Number
  (QUARTER-YEAR-0001) and a multi-file upload widget.
* "Upload & Extract" button sends every uploaded bill to the extraction API
  (/extract), tracks each background job, and automatically pulls the
  results (/job-status, /job-results) into an editable invoice lines table:
  Date, Invoice Number, Supplier, Supplier VAT, Total Amount, VAT Amount,
  Total Incl. VAT.
* "Refresh Job Status" button to re-check jobs that are still processing.
* API Base URL and Bearer Token are stored as system parameters and can be
  changed from VAT Reporting > Configuration > API Settings.
""",
    'author': 'Biztech computer,Alka',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_config_parameter_data.xml',
        'data/vat_report_cron.xml',
        'views/vat_report_views.xml',
        'views/vat_report_config_views.xml',
        'views/vat_report_menus.xml',
    ],
    'application': True,
    'installable': True,
    'auto_install': False,
}
