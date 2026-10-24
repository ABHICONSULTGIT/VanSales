# Part of the Van Sales project.

from odoo import http
from odoo.http import request

from .base import (
    API_PREFIX, ApiError, bool_param, int_param, money, my_van, ok, paginate,
    param, token_required,
)


def product_domain():
    domain = [('sale_ok', '=', True), ('is_storable', '=', True)]
    search = (param('search') or '').strip()
    if search:
        domain += ['|', '|', ('name', 'ilike', search),
                   ('default_code', 'ilike', search),
                   ('barcode', 'ilike', search)]
    category_id = int_param('category_id')
    if category_id:
        domain.append(('categ_id', 'child_of', category_id))
    return domain


def product_item(product, qty, van_policy=False):
    data = {
        'id': product.id,
        'name': product.name,
        'code': product.default_code or None,
        'barcode': product.barcode or None,
        'uom': product.uom_id.name,
        'price': money(product.lst_price),
        'available_qty': qty,
    }
    if van_policy:
        data['oversell'] = product.van_sale_stock_policy_effective or 'warn'
    return data


def warehouse_quantities(warehouse):
    """Free quantity per product in the warehouse stock (on hand - reserved)."""
    groups = request.env['stock.quant']._read_group(
        [('location_id', 'child_of', warehouse.lot_stock_id.id)],
        ['product_id'], ['quantity:sum', 'reserved_quantity:sum'])
    return {product.id: quantity - reserved
            for product, quantity, reserved in groups}


def product_page(quantities, van_policy):
    domain = product_domain()
    if bool_param('in_stock_only', True):
        domain.append(('id', 'in', [pid for pid, qty in quantities.items()
                                    if qty > 0]))
    products, page = paginate(request.env['product.product'], domain,
                              order='name, id')
    return ok([product_item(p, quantities.get(p.id, 0.0), van_policy)
               for p in products], pagination=page)


class VanSalesProductController(http.Controller):

    @http.route(API_PREFIX + '/products/van', type='http', auth='public',
                methods=['GET'], csrf=False, cors='*')
    @token_required
    def van_products(self, **kw):
        van = my_van()
        return product_page(van._van_sales_available_quantities(), True)

    @http.route(API_PREFIX + '/products/warehouse', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    @token_required
    def warehouse_products(self, **kw):
        warehouse = my_van()._van_sales_resolve_warehouse()
        if not warehouse:
            raise ApiError("No warehouse is linked to your van.", 409)
        return product_page(warehouse_quantities(warehouse), False)
