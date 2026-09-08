# Part of the Van Sales project.
"""What a van pulls down as reference data.

Everything is scoped to the device's own van: its routes, the customers on
those routes, the products it may sell and what it is actually carrying. A
device never receives another van's data.
"""

from odoo import api, models

PARAM_PRODUCT_LIMIT = 'van_sales.sync_product_limit'
PARAM_PARTNER_LIMIT = 'van_sales.sync_partner_limit'
DEFAULT_PRODUCT_LIMIT = 5000
DEFAULT_PARTNER_LIMIT = 2000


def _param_int(env, key, default):
    try:
        return max(int(env['ir.config_parameter'].sudo().get_param(key, default)), 1)
    except (TypeError, ValueError):
        return default


def _ids(data, model):
    return [row['id'] for row in data.get(model, [])]


class ResCompany(models.Model):
    _name = 'res.company'
    _inherit = ['res.company', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        return [('id', '=', device.company_id.id)]

    @api.model
    def _van_load_fields(self, device):
        return ['name', 'currency_id', 'country_id', 'vat', 'phone', 'email']


class ResUsers(models.Model):
    _name = 'res.users'
    _inherit = ['res.users', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        return [('id', '=', device.user_id.id)]

    @api.model
    def _van_load_fields(self, device):
        return ['name', 'login', 'partner_id', 'van_sales_lang', 'company_id']


class FleetVehicle(models.Model):
    _name = 'fleet.vehicle'
    _inherit = ['fleet.vehicle', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        return [('id', '=', device.van_id.id)] if device.van_id else False

    @api.model
    def _van_load_fields(self, device):
        return ['name', 'license_plate', 'van_location_id', 'salesman_user_id',
                'cash_journal_id', 'van_warehouse_id', 'company_id']


class VanSalesRoute(models.Model):
    _name = 'van.sales.route'
    _inherit = ['van.sales.route', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        return [('van_id', '=', device.van_id.id)] if device.van_id else False

    @api.model
    def _van_load_fields(self, device):
        return ['name', 'code', 'route_type', 'van_id', 'salesman_user_id',
                'company_id']


class VanSalesRouteLine(models.Model):
    _name = 'van.sales.route.line'
    _inherit = ['van.sales.route.line', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        route_ids = _ids(data, 'van.sales.route')
        return [('route_id', 'in', route_ids)] if route_ids else False

    @api.model
    def _van_load_fields(self, device):
        return ['route_id', 'sequence', 'stop_type', 'partner_id',
                'stop_location_id', 'instruction']

    @api.model
    def _van_load_order(self, device):
        return 'route_id, sequence, id'


class VanSalesStopLocation(models.Model):
    _name = 'van.sales.stop.location'
    _inherit = ['van.sales.stop.location', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        return [('company_id', '=', device.company_id.id)]

    @api.model
    def _van_load_fields(self, device):
        return ['name', 'code', 'street', 'city', 'latitude', 'longitude',
                'note', 'company_id']


class ResPartner(models.Model):
    _name = 'res.partner'
    _inherit = ['res.partner', 'van.sales.load.mixin']

    @api.model
    def _van_partner_ids(self, data, device):
        """Customers this van deals with: everyone on its routes.

        Deliberately not "every customer in the database": a van with 40 shops
        has no business downloading 12,000 contacts over a mobile connection.
        """
        line_rows = data.get('van.sales.route.line', [])
        partner_ids = {row['partner_id'] for row in line_rows if row.get('partner_id')}
        if device.user_id.partner_id:
            partner_ids.add(device.user_id.partner_id.id)
        return partner_ids

    @api.model
    def _van_load_domain(self, data, device):
        partner_ids = self._van_partner_ids(data, device)
        if not partner_ids:
            return False
        return [('id', 'in', list(partner_ids))]

    @api.model
    def _van_load_fields(self, device):
        return ['name', 'ref', 'street', 'street2', 'city', 'zip', 'phone',
                'email', 'vat', 'partner_latitude', 'partner_longitude',
                'property_product_pricelist', 'property_payment_term_id',
                'credit_limit', 'credit', 'company_id', 'active']

    @api.model
    def _van_load_limit(self, device):
        return _param_int(self.env, PARAM_PARTNER_LIMIT, DEFAULT_PARTNER_LIMIT)


class UomUom(models.Model):
    _name = 'uom.uom'
    _inherit = ['uom.uom', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        return []

    @api.model
    def _van_load_fields(self, device):
        return ['name', 'rounding', 'active']


class ProductProduct(models.Model):
    _name = 'product.product'
    _inherit = ['product.product', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        return [('sale_ok', '=', True), ('type', '=', 'consu')]

    @api.model
    def _van_load_fields(self, device):
        return ['name', 'default_code', 'barcode', 'uom_id', 'lst_price',
                'taxes_id', 'categ_id', 'is_storable', 'active',
                'van_sale_stock_policy_effective', 'product_tmpl_id']

    @api.model
    def _van_load_limit(self, device):
        return _param_int(self.env, PARAM_PRODUCT_LIMIT, DEFAULT_PRODUCT_LIMIT)

    @api.model
    def _van_load_order(self, device):
        return 'default_code, name, id'


class ProductCategory(models.Model):
    _name = 'product.category'
    _inherit = ['product.category', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        categ_ids = {row['categ_id'] for row in data.get('product.product', [])
                     if row.get('categ_id')}
        return [('id', 'in', list(categ_ids))] if categ_ids else False

    @api.model
    def _van_load_fields(self, device):
        return ['name', 'complete_name', 'parent_id',
                'van_sale_stock_policy']


class AccountTax(models.Model):
    _name = 'account.tax'
    _inherit = ['account.tax', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        tax_ids = set()
        for row in data.get('product.product', []):
            tax_ids.update(row.get('taxes_id') or [])
        return [('id', 'in', list(tax_ids))] if tax_ids else False

    @api.model
    def _van_load_fields(self, device):
        return ['name', 'amount', 'amount_type', 'price_include_override',
                'type_tax_use', 'company_id', 'active']


class ProductPricelist(models.Model):
    _name = 'product.pricelist'
    _inherit = ['product.pricelist', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        pricelist_ids = {row['property_product_pricelist']
                         for row in data.get('res.partner', [])
                         if row.get('property_product_pricelist')}
        if not pricelist_ids:
            return [('company_id', 'in', (False, device.company_id.id))]
        return [('id', 'in', list(pricelist_ids))]

    @api.model
    def _van_load_fields(self, device):
        return ['name', 'currency_id', 'company_id', 'active']


class ProductPricelistItem(models.Model):
    _name = 'product.pricelist.item'
    _inherit = ['product.pricelist.item', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        pricelist_ids = _ids(data, 'product.pricelist')
        return [('pricelist_id', 'in', pricelist_ids)] if pricelist_ids else False

    @api.model
    def _van_load_fields(self, device):
        return ['pricelist_id', 'applied_on', 'product_tmpl_id', 'product_id',
                'categ_id', 'min_quantity', 'compute_price', 'fixed_price',
                'percent_price', 'price_discount', 'price_surcharge',
                'base', 'date_start', 'date_end']


class StockQuant(models.Model):
    _name = 'stock.quant'
    _inherit = ['stock.quant', 'van.sales.load.mixin']

    @api.model
    def _van_load_domain(self, data, device):
        """What the van is physically carrying, right now."""
        location = device.van_id.van_location_id
        if not location:
            return False
        return [('location_id', 'child_of', location.id)]

    @api.model
    def _van_load_fields(self, device):
        return ['product_id', 'location_id', 'quantity', 'reserved_quantity']
