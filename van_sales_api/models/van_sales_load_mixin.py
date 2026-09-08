# Part of the Van Sales project.

from odoo import api, models
from odoo.fields import Domain


class VanSalesLoadMixin(models.AbstractModel):
    """Declarative loader for everything a van pulls down.

    Modelled on Odoo's own ``pos.load.mixin``: each model states *which*
    records a device may see and *which* fields it gets, and the framework
    applies the delta watermark on top. The server therefore sends one
    explicit, scoped dataset rather than exposing the ORM.

    ``_van_load_domain`` receives the response accumulated so far, so a later
    model can filter on ids already selected - route lines on their routes,
    invoices on the customers actually being sent, and so on.
    """

    _name = 'van.sales.load.mixin'
    _description = "Van Sales Sync Loader"

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------
    @api.model
    def _van_load_domain(self, data, device):
        """Records this device may see. Return False to send nothing."""
        return []

    @api.model
    def _van_load_fields(self, device):
        """Fields to send. Empty means the model is skipped."""
        return []

    @api.model
    def _van_load_limit(self, device):
        return None

    @api.model
    def _van_load_order(self, device):
        return None

    # ------------------------------------------------------------------
    # Framework
    # ------------------------------------------------------------------
    @api.model
    def _van_watermark_domain(self, domain):
        """Narrow to what changed since the device's last successful pull.

        A plain ``write_date >`` watermark, exactly as POS does it. The
        watermark itself is the server's transaction start time, so it is
        consistent rather than drifting mid-request.
        """
        watermark = self.env.context.get('van_sales_watermark')
        if domain is False or not watermark:
            return domain
        return Domain.AND([Domain(domain), Domain('write_date', '>', watermark)])

    @api.model
    def _van_load_search_read(self, data, device):
        fields_to_send = self._van_load_fields(device)
        if not fields_to_send:
            return []
        domain = self._van_load_domain(data, device)
        if domain is False:
            return []
        domain = self._van_watermark_domain(domain)
        records = self.sudo().search(
            domain,
            limit=self._van_load_limit(device),
            order=self._van_load_order(device))
        return self._van_load_read(records, device)

    @api.model
    def _van_load_read(self, records, device):
        fields_to_send = self._van_load_fields(device)
        if not fields_to_send or not records:
            return []
        # load=False returns many2one as a bare id rather than (id, name):
        # the client keeps its own relational store and resolves names itself.
        return records.read(fields_to_send, load=False)

    def _van_irrelevant_ids(self, device):
        """Of these records, which the device should drop.

        Archived records still exist, so ``exists()`` alone will not catch
        them - the device would keep showing a customer the office retired.
        """
        if 'active' not in self._fields:
            return []
        return self.filtered(lambda record: not record.active).ids
