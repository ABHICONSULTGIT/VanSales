# VAT REPORT LINE — FIXED BUILD 2026-07-28-v9
# Handles nested API response: seller_details / invoice_details / vat_details / item_details
import json
import logging
import re
from datetime import datetime

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

SUBUNIT_1000_CURRENCIES = {'BHD', 'KWD', 'OMR', 'JOD', 'TND', 'LYD'}

# Keywords in seller city/address/state that indicate a BHD/GCC-zone country
BHD_GEO_KEYWORDS = {'bahrain', 'manama', 'muharraq', 'riffa', 'hamad', 'isa town'}
KWD_GEO_KEYWORDS = {'kuwait', 'kuwait city', 'salmiya', 'hawalli'}
OMR_GEO_KEYWORDS = {'oman', 'muscat', 'salalah', 'sohar'}
JOD_GEO_KEYWORDS = {'jordan', 'amman', 'zarqa', 'irbid'}

# Phone country codes → currency
_PHONE_CODE_CURRENCY = {
    '+973': 'BHD',   # Bahrain
    '+965': 'KWD',   # Kuwait
    '+968': 'OMR',   # Oman
    '+962': 'JOD',   # Jordan
    '+971': '',      # UAE (AED — not a subunit currency, skip)
    '+966': '',      # Saudi (SAR — not subunit, skip)
}

# Currency-label strings that explicitly indicate BHD/KWD/OMR/JOD
_CURRENCY_LABEL_MAP = [
    # BHD
    (' bd ', 'BHD'), ('bd.', 'BHD'), ('b.d.', 'BHD'), ('bhd', 'BHD'),
    ('bahraini dinar', 'BHD'), ('bahrain dinar', 'BHD'),
    # KWD
    (' kd ', 'KWD'), ('kwd', 'KWD'), ('kuwaiti dinar', 'KWD'),
    # OMR
    (' ro ', 'OMR'), ('omr', 'OMR'), ('omani rial', 'OMR'),
    # JOD
    (' jd ', 'JOD'), ('jod', 'JOD'), ('jordanian dinar', 'JOD'),
]


# Document title patterns indicating return/credit note
_CN_PATTERNS = [
    re.compile(r'\bcredit\s*note\b', re.I),
    re.compile(r'\btax\s*credit\s*note\b', re.I),
    re.compile(r'\bsales\s*return\b', re.I),
    re.compile(r'\bcredit\s*memo\b', re.I),
    re.compile(r'\breturn\s*invoice\b', re.I),
    re.compile(r'\bcn\b', re.I),
]


def _has_credit_note_title(data):
    if not isinstance(data, dict):
        return False
    raw_texts = []
    for key in ('header_from_document', 'footer_from_document', 'terms_and_conditions'):
        val = data.get(key)
        if isinstance(val, str):
            raw_texts.append(val)
    for key, val in data.items():
        if isinstance(val, dict):
            for sub_key in ('header_from_document', 'footer_from_document', 'terms_and_conditions'):
                sub_val = val.get(sub_key)
                if isinstance(sub_val, str):
                    raw_texts.append(sub_val)
    for text in raw_texts:
        for pattern in _CN_PATTERNS:
            if pattern.search(text):
                return True
    return False


def _to_float(value):
    """
    Convert a string/number to float.
    The API consistently uses dot as decimal separator (e.g. "2.760" = 2.760 BHD).
    We simply strip currency symbols, spaces, and commas (thousands separator),
    then parse the result as a standard float.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    # Remove currency symbols and spaces; keep digits, dot, comma, minus
    s = re.sub(r'[^\d.,\-]', '', s)
    if not s:
        return 0.0

    has_dot   = '.' in s
    has_comma = ',' in s

    if has_dot and has_comma:
        # Both separators present — determine which is decimal by last position
        last_dot   = s.rfind('.')
        last_comma = s.rfind(',')
        if last_comma > last_dot:
            # European: "12.047,04" — dot=thousands, comma=decimal
            s = s.replace('.', '').replace(',', '.')
        else:
            # Standard: "12,047.04" — comma=thousands, dot=decimal
            s = s.replace(',', '')
    elif has_comma and not has_dot:
        # Only commas — strip if multiple (thousands), replace if single and
        # not 3-digit-group (decimal comma)
        if s.count(',') > 1:
            s = s.replace(',', '')
        else:
            after_comma = s.split(',')[-1]
            if len(after_comma) == 3:
                s = s.replace(',', '')   # thousands comma: "12,047"
            else:
                s = s.replace(',', '.')  # decimal comma:   "12,04"
    # If only dots are present, treat them as decimal (standard API format)
    # e.g. "2.760" BHD stays as 2.760, not 2760

    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0



def _detect_currency_from_geo(seller, extra_text=''):
    """
    Detect the currency from seller geo fields and any additional text.
    Scanning order (most-reliable first):
      1. Explicit currency labels ('BD', 'BHD', 'KD', …)
      2. Phone country codes (+973, +965, …)
      3. City / country geo keywords
    Accepts:
      seller     – dict of seller fields from the API response
      extra_text – additional free-form text (e.g. full entry dump)
    Returns a currency code string or '' if not detected.
    """
    if not isinstance(seller, dict) and not extra_text:
        return ''

    # Collect ALL string values from the seller dict (any key)
    parts = []
    if isinstance(seller, dict):
        for v in seller.values():
            if isinstance(v, str) and v:
                parts.append(v)
            elif isinstance(v, dict):
                # one level deeper
                for vv in v.values():
                    if isinstance(vv, str) and vv:
                        parts.append(vv)
    if extra_text:
        parts.append(extra_text)

    geo_text = ' '.join(parts).lower()

    # 1. Explicit currency labels
    for label, code in _CURRENCY_LABEL_MAP:
        if label in geo_text:
            return code

    # 2. Phone country code (+973, +965, …)
    for code_str, currency in _PHONE_CODE_CURRENCY.items():
        if code_str in geo_text and currency:
            return currency

    # 3. Geo keywords
    if any(k in geo_text for k in BHD_GEO_KEYWORDS):
        return 'BHD'
    if any(k in geo_text for k in KWD_GEO_KEYWORDS):
        return 'KWD'
    if any(k in geo_text for k in OMR_GEO_KEYWORDS):
        return 'OMR'
    if any(k in geo_text for k in JOD_GEO_KEYWORDS):
        return 'JOD'
    return ''


def _detect_currency_from_entry(entry):
    """
    Last-resort currency detection: collect all string values from the
    entire API entry dict and pass them to _detect_currency_from_geo.
    """
    if not isinstance(entry, dict):
        return ''
    texts = []
    def _collect(obj, depth=0):
        if depth > 4:
            return
        if isinstance(obj, str):
            texts.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                _collect(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                _collect(item, depth + 1)
    _collect(entry)
    return _detect_currency_from_geo({}, extra_text=' '.join(texts))


def _normalise_amount(value, currency_code):
    """
    For invoice-level total fields (invoice_value, grand total).
    BHD/KWD/OMR/JOD amounts may come in as subunits (fils).
    e.g. 3000 fils = BD 3.000, or 44000.0 fils = BD 44.000
    Divide by 1000 when:
      - the raw value is an integer (no decimal point in string), OR
      - the raw value is an integer-valued float (e.g. 44000.0, 19500.0)
        which Python always serialises with a trailing '.0'
    If the API returns "3.750" (a genuine fractional BHD amount)
    _to_float gives 3.75 — already in major units, so we leave it alone.
    """
    amount = _to_float(value)
    if currency_code and currency_code.upper() in SUBUNIT_1000_CURRENCIES:
        raw_str = str(value).split('e')[0]  # handle scientific notation
        # No decimal/comma → definitely an integer in subunits
        if '.' not in raw_str and ',' not in raw_str:
            return round(amount / 1000.0, 3)
        # Float but with no fractional part (e.g. 44000.0, 19500.0) → subunits
        if isinstance(value, float) and value == int(value):
            return round(amount / 1000.0, 3)
    return amount


def _normalise_item_amount(value, currency_code):
    """
    For item-level fields (item_value, gst_amount, vat_amount etc.).
    These are always in major currency units — the API gives item prices
    as real numbers like 25.000 or 16.5, NOT in subunit integers.
    Only divide by 1000 when the raw value is a pure integer string
    with no decimal separator at all (extremely rare edge case).
    """
    amount = _to_float(value)
    if currency_code and currency_code.upper() in SUBUNIT_1000_CURRENCIES:
        raw_str = str(value).split('e')[0]
        if '.' not in raw_str and ',' not in raw_str and isinstance(value, int):
            return round(amount / 1000.0, 3)
    return amount



def _to_date(value):
    if not value:
        return False
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    # 4-digit year formats — try first (most unambiguous)
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y',
                '%d.%m.%Y', '%d-%b-%Y', '%d %b %Y', '%B %d, %Y',
                '%m/%d/%Y', '%m-%d-%Y'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # 2-digit year formats — GCC/Bahrain bills often write DD-MM-YY or DD/MM/YY
    # Day-first variants are listed first to match regional convention.
    # Python maps 2-digit years: 00-68 → 2000-2068, 69-99 → 1969-1999.
    for fmt in ('%d-%m-%y', '%d/%m/%y', '%d.%m.%y',
                '%y-%m-%d', '%y/%m/%d',
                '%m-%d-%y', '%m/%d/%y'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        from dateutil import parser as dp
        return dp.parse(text, dayfirst=True, fuzzy=True).date()
    except Exception:
        _logger.warning('VAT Reporting: cannot parse date %r', value)
        return False


def _get(d, *keys):
    """Return first non-null value from dict d for any of the given keys.
    First tries exact key match, then case-insensitive match (handles APIs
    that return uppercase keys like 'VAT' when we look for 'vat').
    """
    if not isinstance(d, dict):
        return None
    # Build a lowercase-key → actual-value map for case-insensitive fallback
    lower_map = {k.lower(): v for k, v in d.items()}
    for k in keys:
        # 1. Exact match (fast path)
        v = d.get(k)
        if v not in (None, '', 'null'):
            return v
        # 2. Case-insensitive match
        v = lower_map.get(k.lower())
        if v not in (None, '', 'null'):
            return v
    return None


def _parse_nested(entry, company_currency=''):
    """
    Parse the actual API response structure:
      seller_details  -> supplier name, VAT number, geo (for currency detection)
      invoice_details -> invoice_number, invoice_date, invoice_value, invoice_currency
      vat_details     -> VAT Amount
      item_details[]  -> fallback if invoice_value is missing
      invoice_summary / totals -> fallback grand_total if invoice_value is missing
    """
    seller  = entry.get('seller_details') or {}
    invoice = entry.get('invoice_details') or {}
    vat     = entry.get('vat_details') or {}
    items   = entry.get('item_details') or []

    # Currency priority:
    #   1. invoice_currency declared in the invoice
    #   2. detected from seller's geographic info (city/address)
    #   3. company currency as last resort
    invoice_cur  = (_get(invoice, 'invoice_currency') or '').upper().strip()

    # Normalize non-standard short codes the API sometimes returns
    _CURRENCY_ALIASES = {
        'BD': 'BHD',   # Bahrain Dinar
        'KD': 'KWD',   # Kuwait Dinar
        'RO': 'OMR',   # Oman Rial
        'JD': 'JOD',   # Jordan Dinar
        'SR': 'SAR',   # Saudi Riyal
        'QR': 'QAR',   # Qatar Riyal
        'AED': 'AED',  # UAE Dirham (already correct)
    }
    invoice_cur = _CURRENCY_ALIASES.get(invoice_cur, invoice_cur)

    geo_cur      = _detect_currency_from_geo(seller) if not invoice_cur else ''
    cur          = invoice_cur or geo_cur or company_currency or ''

    _logger.info('VAT Reporting: currency resolution: invoice_cur=%r geo_cur=%r '
                 'company_cur=%r → using %r', invoice_cur, geo_cur, company_currency, cur)

    supplier_name = _get(seller, 'seller_name', 'company_name', 'vendor_name')
    # Prefer explicit VAT/TRN from seller_details, then vat_details section
    # Covers all common key names used by different OCR API versions/vendors
    supplier_vat  = (
        _get(seller, 'seller_gst', 'seller_vat', 'vat_number',
             'seller_vat_number', 'seller_trn', 'trn',
             'tax_registration_number', 'vat_registration_number',
             'seller_tax_number', 'seller_tin', 'tin',
             'vat_no', 'seller_vat_no', 'vat',
             # Additional key variants seen in real API responses:
             'seller_vat_no', 'company_vat', 'company_trn',
             'seller_registration_number', 'vat_reg_no',
             'tax_id', 'tax_number', 'gst_number') or
        _get(vat, 'Seller VAT No./ VAT TIN', 'Seller CST No./ CST TIN',
             'seller_vat', 'vat_number', 'trn', 'vat_registration_number',
             'VAT No', 'vat_no', 'registration_number') or
        _get(invoice, 'seller_vat', 'seller_trn', 'seller_vat_number',
             'vat_number', 'vat_no', 'tax_number', 'registration_number')
    )
    # If still not found, attempt regex extraction from raw text fields
    # e.g. "VAT: 220001271400002" or "TRN: 100123456700003" printed on bill
    if not supplier_vat:
        supplier_vat = _extract_vat_from_text(entry)
    # Filter out placeholder strings the API sometimes returns
    if supplier_vat and str(supplier_vat).lower() in ('null', 'none', 'n/a', '-', 'n.a.', ''):
        supplier_vat = None

    inv_number = _get(invoice, 'invoice_number', 'invoice_no', 'bill_number')
    inv_date   = _to_date(_get(invoice, 'invoice_date', 'bill_date', 'date'))

    # ── Track whether any amount was derived/calculated vs. read directly ──
    # When True, the system had to fill in missing values, meaning the API
    # could not read all amounts reliably — line will be highlighted.
    amounts_derived = False

    # 1. Grand Total (Incl. VAT) — invoice_value is authoritative
    raw_iv = _get(invoice, 'invoice_value', 'total_amount', 'net_amount', 'taxable_amount')
    summary = entry.get('invoice_summary') or entry.get('totals') or {}
    if raw_iv is None:
        raw_iv = _get(summary, 'grand_total', 'total_value', 'invoice_total', 'total')

    # If invoice_value was not directly provided by the API, we will have to derive it
    grand_total_from_api = raw_iv is not None
    grand_total = _normalise_amount(raw_iv, cur) if raw_iv is not None else 0.0

    # Smart subunit detection for grand_total in BHD/KWD etc.
    cur_upper = cur.upper() if cur else ''
    is_subunit_currency = cur_upper in SUBUNIT_1000_CURRENCIES
    if is_subunit_currency and raw_iv is not None:
        raw_float = _to_float(raw_iv)
        is_integer_valued = (isinstance(raw_iv, float) and raw_float == int(raw_float) and raw_float > 0) or (isinstance(raw_iv, int) and raw_float > 0)
        
        if is_integer_valued:
            # Compute item_sum as a cross-reference (items are always in major units)
            item_sum = 0.0
            for _item in items:
                if not isinstance(_item, dict): continue
                _iv = _get(_item, 'item_value', 'line_total', 'amount', 'total')
                if _iv is not None: item_sum += _normalise_item_amount(_iv, cur)
            
            divided = raw_float / 1000.0
            if item_sum > 0.0:
                ratio_direct  = raw_float / item_sum
                ratio_divided = divided / item_sum
                closer_to_divided = abs(ratio_divided - 1.0) < abs(ratio_direct - 1.0)
                grand_total = round(divided, 3) if closer_to_divided else raw_float
            else:
                grand_total = round(divided, 3) if raw_float >= 1000.0 else raw_float

    # 2. Excl VAT — sum of item values is authoritative, fallback to subtotal
    excl_vat = 0.0
    for _item in items:
        if not isinstance(_item, dict): continue
        _iv = _get(_item, 'item_value', 'line_total', 'amount', 'total')
        if _iv is not None: excl_vat += _normalise_item_amount(_iv, cur)
        
    if excl_vat == 0.0:
        raw_sub = _get(summary, 'sub_total', 'subtotal')
        if raw_sub is not None: excl_vat = _normalise_amount(raw_sub, cur)

    excl_vat_from_api = excl_vat > 0.0  # True if items/subtotal gave us a value

    # 3. VAT amount
    raw_vat = _get(vat, 'VAT Amount', 'vat_amount', 'tax_amount')
    if raw_vat is not None:
        vat_amount = _normalise_item_amount(raw_vat, cur)
        vat_from_api = True
    else:
        vat_amount = 0.0
        vat_from_api = False
        for item in items:
            if not isinstance(item, dict): continue
            tax = _get(item, 'gst_amount', 'vat_amount', 'igst_amount', 'cgst_amount', 'sgst_amount', 'utgst_amount', 'tax_amount')
            if tax is not None:
                vat_amount += _normalise_item_amount(tax, cur)
                vat_from_api = True
            
        if vat_amount == 0.0:
            for item in items:
                if not isinstance(item, dict): continue
                rate_raw = _get(item, 'gst_rate', 'vat_rate', 'tax_rate')
                iv_raw   = _get(item, 'item_value', 'line_total', 'amount')
                if rate_raw is not None and iv_raw is not None:
                    vat_amount += round(_normalise_item_amount(iv_raw, cur) * _to_float(rate_raw) / 100.0, 3)

    # Reconciliation — each step that fills in a missing value sets amounts_derived=True
    if grand_total > 0 and excl_vat > 0 and vat_amount == 0:
        calculated_vat = round(grand_total - excl_vat, 3)
        if calculated_vat > 0:
            # Sanity check: VAT shouldn't be > 25% of Excl VAT.
            # If it is, the OCR likely returned a garbage grand_total.
            if (calculated_vat / excl_vat) <= 0.25:
                vat_amount = calculated_vat
                amounts_derived = True  # VAT was calculated, not read from API
            else:
                grand_total = excl_vat
                amounts_derived = True  # grand_total overridden (OCR garbage)

    if grand_total > 0 and vat_amount > 0 and excl_vat == 0:
        excl_vat = round(grand_total - vat_amount, 3)
        amounts_derived = True  # excl_vat was derived: grand_total - vat
        
    if excl_vat > 0 and vat_amount > 0 and grand_total == 0:
        grand_total = round(excl_vat + vat_amount, 3)
        amounts_derived = True  # grand_total was derived: excl_vat + vat
        
    if grand_total == 0 and excl_vat > 0 and vat_amount == 0:
        grand_total = excl_vat
        amounts_derived = True  # grand_total guessed from excl_vat alone

    # Sanity check: if amounts don't add up, the API read inconsistent values
    if abs(grand_total - (excl_vat + vat_amount)) > 0.01:
        amounts_derived = True  # values from API are inconsistent — flag for review
        # Priority: grand_total and excl_vat are the most reliably OCR-read figures
        # (printed as large, clear totals on invoices). When both came from the API,
        # trust them and derive VAT as the difference — never override grand_total.
        if grand_total_from_api and excl_vat_from_api and grand_total >= excl_vat:
            # e.g. grand_total=37.04, excl_vat=34.00, wrong vat=0.36 → vat=3.04
            vat_amount = round(grand_total - excl_vat, 3)
        elif grand_total_from_api and excl_vat_from_api and grand_total < excl_vat:
            # Discount pushed total below subtotal — treat as zero VAT
            vat_amount = 0.0
        elif grand_total_from_api and excl_vat > 0 and vat_amount > 0:
            # grand_total from API is authoritative; recalc excl_vat from it
            excl_vat = round(grand_total - vat_amount, 3) if grand_total >= vat_amount else grand_total
        elif excl_vat > 0 and vat_amount > 0:
            # Neither total was from API — derive grand_total from the other two
            grand_total = round(excl_vat + vat_amount, 3)
        else:
            excl_vat = grand_total - vat_amount if grand_total >= vat_amount else grand_total


    total_amount = excl_vat

    _logger.info('VAT Reporting: parsed amounts — total=%s vat=%s cur=%s derived=%s',
                 total_amount, vat_amount, cur, amounts_derived)

    return {
        'date':                inv_date,
        'invoice_number':      inv_number,
        'supplier':            supplier_name,
        'supplier_vat':        supplier_vat,
        'total_amount':        total_amount,
        'vat_amount':          vat_amount,
        'total_including_vat': total_amount + vat_amount,
        'amounts_derived':     amounts_derived,
    }


# Regex to extract a VAT/TRN number from raw text.
# Matches many label variants found on GCC/Bahrain invoices:
#   "VAT:", "VAT No.", "VAT No:", "VAT Number", "VAT#",
#   "Client VAT No.", "Buyer VAT No.", "Customer VAT",
#   "TRN:", "Tax Reg No:", "Tax Registration Number", "Tax Invoice No"
# followed by 8-20 alphanumeric characters (the actual registration number).
_VAT_TEXT_RE = re.compile(
    r'(?:'
    r'(?:Client|Buyer|Customer|Seller|Supplier|Company)?\s*'
    r'(?:VAT|TRN|Tax\s*Reg(?:istration)?|GST)'
    r'(?:\s*(?:No\.?|Number|#|ID|Registration|Reg\.?))?'
    r'|Tax\s*Invoice\s*No\.?'
    r')'
    r'[:\s#=]*([A-Z0-9]{8,20})',
    re.I
)


def _extract_vat_from_text(data):
    """
    Scan ALL string fields in the API response for a printed VAT / TRN
    registration number pattern (e.g. "VAT No. 200012064800002" or
    "Client VAT No. 220001271400002").
    Searches top-level, one level deep (nested dicts), and explicit priority
    fields so that we catch VAT numbers regardless of which JSON key the
    OCR engine chose to put them in.
    Returns the first match found, or None.
    """
    if not isinstance(data, dict):
        return None

    # Priority text fields to check first (most likely to contain printed VAT labels)
    _PRIORITY_KEYS = (
        'header_from_document', 'footer_from_document', 'terms_and_conditions',
        'seller_address', 'seller_details_text', 'raw_text', 'ocr_text',
        'description', 'notes', 'seller_info', 'company_details',
        'invoice_text', 'full_text',
    )

    def _scan_texts(texts):
        for text in texts:
            if not isinstance(text, str) or not text.strip():
                continue
            m = _VAT_TEXT_RE.search(text)
            if m:
                candidate = m.group(1).strip()
                _logger.info('VAT Reporting: extracted VAT from text: %r', candidate)
                return candidate
        return None

    # Pass 1 — priority keys at top level
    result = _scan_texts(data.get(k) for k in _PRIORITY_KEYS)
    if result:
        return result

    # Pass 2 — priority keys inside each nested dict
    for val in data.values():
        if isinstance(val, dict):
            result = _scan_texts(val.get(k) for k in _PRIORITY_KEYS)
            if result:
                return result

    # Pass 3 — ALL string values at top level (catch-all)
    result = _scan_texts(v for v in data.values() if isinstance(v, str))
    if result:
        return result

    # Pass 4 — ALL string values inside nested dicts (deepest catch-all)
    for val in data.values():
        if isinstance(val, dict):
            result = _scan_texts(v for v in val.values() if isinstance(v, str))
            if result:
                return result

    # Pass 5 — bare GCC-style VAT numbers (10-15 digit sequences) in
    # ALL string values, even without a label prefix.
    # GCC VAT numbers are typically 15 digits.
    # Only match strings that are PURELY digits (already extracted by OCR API).
    _BARE_VAT_RE = re.compile(r'^\d{10,15}$')
    for val in data.values():
        if isinstance(val, str) and _BARE_VAT_RE.match(val.strip()):
            candidate = val.strip()
            _logger.info('VAT Reporting: bare VAT from top-level string: %r', candidate)
            return candidate
    for val in data.values():
        if isinstance(val, dict):
            for vv in val.values():
                if isinstance(vv, str) and _BARE_VAT_RE.match(vv.strip()):
                    candidate = vv.strip()
                    _logger.info('VAT Reporting: bare VAT from nested string: %r', candidate)
                    return candidate

    return None


def _parse_flat(entry, currency_code=''):
    """Fallback for flat/legacy API responses (no seller_details nesting)."""
    cur = currency_code or ''

    def _first(*keys):
        lower_map = {k.lower(): v for k, v in entry.items()}
        for k in keys:
            v = entry.get(k)
            if v not in (None, ''):
                return v
            v = lower_map.get(k.lower())
            if v not in (None, ''):
                return v
        return None


    total  = _normalise_amount(_first('total_amount', 'subtotal', 'net_amount', 'taxable_amount'), cur)
    vat    = _normalise_amount(_first('vat_amount', 'tax_amount', 'vat', 'tax'), cur)
    t_raw  = _first('total_include_vat', 'total_including_vat', 'grand_total')
    # If grand_total not provided, it was calculated — flag for review
    t_incl = _normalise_amount(t_raw, cur) if t_raw is not None else (total + vat)
    amounts_derived = t_raw is None and (total > 0 or vat > 0)

    # Expanded key list + regex fallback for VAT/TRN number
    flat_vat = _first(
        'supplier_vat', 'vat_number', 'trn',
        'seller_vat', 'seller_trn', 'seller_vat_number',
        'tax_registration_number', 'vat_registration_number',
        'seller_tin', 'tin', 'vat_no',
    ) or _extract_vat_from_text(entry)
    if flat_vat and str(flat_vat).lower() in ('null', 'none', 'n/a', '-', 'n.a.', ''):
        flat_vat = None

    return {
        'date':                _to_date(_first('date', 'invoice_date', 'bill_date')),
        'invoice_number':      _first('invoice_number', 'invoice_no', 'bill_number', 'number'),
        'supplier':            _first('supplier', 'supplier_name', 'vendor', 'seller_name'),
        'supplier_vat':        flat_vat,
        'total_amount':        total,
        'vat_amount':          vat,
        'total_including_vat': t_incl,
        'amounts_derived':     amounts_derived,
    }


class VatReportLine(models.Model):
    _name = 'vat.report.line'
    _description = 'VAT Report Invoice Line'
    _rec_name = 'invoice_number'
    _order = 'date asc, id asc'

    report_id           = fields.Many2one('vat.report', required=True, ondelete='cascade')
    job_id              = fields.Many2one('vat.report.job', string='Source Job', ondelete='set null')
    currency_id         = fields.Many2one(related='report_id.currency_id', readonly=True)
    date                = fields.Date(string='Date')
    invoice_number      = fields.Char(string='Invoice Number')
    supplier            = fields.Char(string='Supplier')
    supplier_vat        = fields.Char(string='Supplier VAT')
    total_amount        = fields.Monetary(string='Total Amount')
    vat_amount          = fields.Monetary(string='VAT Amount')
    total_including_vat = fields.Monetary(string='Total Incl. VAT')
    invoice_type        = fields.Selection([
        ('sales_invoice', 'Sales Invoice'),
        ('sales_return', 'Sales Return'),
        ('purchase_invoice', 'Purchase Invoice'),
        ('purchase_return', 'Purchase Return'),
    ], string='Invoice Type', default='purchase_invoice', required=True)
    raw_data            = fields.Text(string='Raw API Data')
    parse_warning       = fields.Boolean(
        string='Needs Review',
        compute='_compute_parse_warning',
        store=True,
        readonly=False,
        help='Set automatically when the API could not fully understand the document '
             '(e.g. missing invoice number, supplier, or date). '
             'Please review and correct this line manually.')

    @api.depends('date', 'invoice_number', 'supplier', 'total_amount', 'vat_amount', 'total_including_vat')
    @api.onchange('date', 'invoice_number', 'supplier', 'total_amount', 'vat_amount', 'total_including_vat')
    def _compute_parse_warning(self):
        for rec in self:
            missing_date = not rec.date
            missing_inv  = not rec.invoice_number or not str(rec.invoice_number).strip()
            missing_supp = not rec.supplier or not str(rec.supplier).strip()
            zero_amounts = (
                (rec.total_amount or 0.0) == 0.0 and
                (rec.vat_amount or 0.0) == 0.0 and
                (rec.total_including_vat or 0.0) == 0.0
            )
            rec.parse_warning = bool(missing_date or missing_inv or missing_supp or zero_amounts)

    @api.onchange('invoice_type', 'total_amount', 'vat_amount')
    def _onchange_amounts_and_type(self):
        for rec in self:
            is_return = rec.invoice_type in ('sales_return', 'purchase_return')
            if is_return:
                if rec.total_amount and rec.total_amount > 0:
                    rec.total_amount = -abs(rec.total_amount)
                if rec.vat_amount and rec.vat_amount > 0:
                    rec.vat_amount = -abs(rec.vat_amount)
            else:
                if rec.total_amount and rec.total_amount < 0:
                    rec.total_amount = abs(rec.total_amount)
                if rec.vat_amount and rec.vat_amount < 0:
                    rec.vat_amount = abs(rec.vat_amount)

            tot = rec.total_amount or 0.0
            vat = rec.vat_amount or 0.0
            rec.total_including_vat = tot + vat

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            inv_type = vals.get('invoice_type')
            if inv_type in ('sales_return', 'purchase_return'):
                if 'total_amount' in vals and vals['total_amount']:
                    vals['total_amount'] = -abs(vals['total_amount'])
                if 'vat_amount' in vals and vals['vat_amount']:
                    vals['vat_amount'] = -abs(vals['vat_amount'])
                if 'total_including_vat' in vals and vals['total_including_vat']:
                    vals['total_including_vat'] = -abs(vals['total_including_vat'])
            elif inv_type in ('sales_invoice', 'purchase_invoice'):
                if 'total_amount' in vals and vals['total_amount']:
                    vals['total_amount'] = abs(vals['total_amount'])
                if 'vat_amount' in vals and vals['vat_amount']:
                    vals['vat_amount'] = abs(vals['vat_amount'])
                if 'total_including_vat' in vals and vals['total_including_vat']:
                    vals['total_including_vat'] = abs(vals['total_including_vat'])
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        for rec in self:
            if rec.invoice_type in ('sales_return', 'purchase_return'):
                to_update = {}
                if rec.total_amount and rec.total_amount > 0:
                    to_update['total_amount'] = -abs(rec.total_amount)
                if rec.vat_amount and rec.vat_amount > 0:
                    to_update['vat_amount'] = -abs(rec.vat_amount)
                if rec.total_including_vat and rec.total_including_vat > 0:
                    to_update['total_including_vat'] = -abs(rec.total_including_vat)
                if to_update:
                    super(VatReportLine, rec).write(to_update)
            elif rec.invoice_type in ('sales_invoice', 'purchase_invoice'):
                to_update = {}
                if rec.total_amount and rec.total_amount < 0:
                    to_update['total_amount'] = abs(rec.total_amount)
                if rec.vat_amount and rec.vat_amount < 0:
                    to_update['vat_amount'] = abs(rec.vat_amount)
                if rec.total_including_vat and rec.total_including_vat < 0:
                    to_update['total_including_vat'] = abs(rec.total_including_vat)
                if to_update:
                    super(VatReportLine, rec).write(to_update)
        return res

    # All top-level keys the API uses to wrap invoice header data
    _HEADER_WRAPPER_KEYS = (
        'invoice_header',   # documented format
        'header_details',   # variant 1
        'header_data',      # variant 2
        'header',           # variant 3
        'invoice_data',     # variant 4
    )

    @api.model
    def create_from_api(self, report_id, job_id, entry):
        """Create one invoice line from one results entry returned by the API."""
        if not isinstance(entry, dict):
            _logger.warning('VAT Reporting: non-dict entry skipped: %r', entry)
            return False

        report      = self.env['vat.report'].browse(report_id)
        company_cur = report.currency_id.name if report.currency_id else ''

        # ── Handle error entries that wrap the actual JSON in 'raw_response' ──
        # Some OCR failures return: {"error": "...", "raw_response": "{...}", "exception": "..."}
        # Try to extract and parse the embedded JSON from raw_response.
        if 'error' in entry and 'raw_response' in entry:
            raw_str = entry.get('raw_response') or ''
            parsed_raw = None
            if raw_str and isinstance(raw_str, str):
                try:
                    parsed_raw = json.loads(raw_str)
                except (ValueError, TypeError):
                    pass
            if isinstance(parsed_raw, dict) and parsed_raw:
                _logger.info('VAT Reporting: recovered data from raw_response for error entry')
                entry = parsed_raw
            else:
                _logger.warning('VAT Reporting: error entry with no recoverable data: %s',
                                entry.get('error'))
                return False

        # ── Unwrap any top-level header wrapper key ────────────────────────
        # The API uses several different wrapper key names depending on version/vendor:
        #   invoice_header / header_details / header_data / header / invoice_data
        # All wrap: seller_details, invoice_details, vat_details, etc.
        parse_entry = entry
        for wrapper_key in self._HEADER_WRAPPER_KEYS:
            if wrapper_key in entry:
                header = entry[wrapper_key] or {}
                if not isinstance(header, dict):
                    continue
                # item_details may be at root level OR inside the wrapper
                item_details = (entry.get('item_details')
                                or header.get('item_details') or [])
                # Merge: start from header content, then set item_details
                unwrapped = dict(header)
                unwrapped['item_details'] = item_details
                # Also pull in any top-level summary sections
                for summary_key in ('invoice_summary', 'totals'):
                    if summary_key in entry and summary_key not in unwrapped:
                        unwrapped[summary_key] = entry[summary_key]
                # Preserve top-level text fields so _extract_vat_from_text
                # can still find VAT numbers printed in header/footer/address
                # text that the API put at the root of the response.
                _TEXT_PRESERVE = (
                    'header_from_document', 'footer_from_document',
                    'terms_and_conditions', 'raw_text', 'ocr_text',
                    'seller_address', 'seller_details_text',
                    'description', 'notes', 'full_text', 'invoice_text',
                )
                for _tk in _TEXT_PRESERVE:
                    if _tk in entry and _tk not in unwrapped:
                        unwrapped[_tk] = entry[_tk]
                _logger.info('VAT Reporting: unwrapped %r wrapper, keys=%s',
                             wrapper_key, list(unwrapped.keys()))
                parse_entry = unwrapped
                break

        is_nested = any(k in parse_entry for k in
                        ('seller_details', 'invoice_details', 'vat_details', 'item_details'))

        _logger.info('VAT Reporting: BUILD=2026-07-28-v9 nested=%s company_cur=%s keys=%s',
                     is_nested, company_cur, list(parse_entry.keys()))

        parsed = _parse_nested(parse_entry, company_cur) if is_nested \
            else _parse_flat(parse_entry, company_cur)

        # ── Last-resort VAT number extraction ─────────────────────────────
        # _parse_nested/_parse_flat scan `parse_entry` (the unwrapped version).
        # If the API put the VAT label text at the TOP level of the original
        # response (outside the wrapper key), it was lost during unwrapping.
        # Scan the ORIGINAL `entry` here as a final safety net.
        if not parsed.get('supplier_vat'):
            vat_from_original = _extract_vat_from_text(entry)
            if vat_from_original:
                _logger.info('VAT Reporting: VAT number found in original entry: %r',
                             vat_from_original)
                parsed['supplier_vat'] = vat_from_original

        _logger.info('VAT Reporting: final parsed=%s', parsed)

        report_type = report.invoice_type or 'purchase_invoice'
        total_amount = parsed.get('total_amount', 0.0) or 0.0
        total_incl = parsed.get('total_including_vat', 0.0) or 0.0
        is_negative = total_amount < 0.0 or total_incl < 0.0
        is_cn_title = _has_credit_note_title(entry)

        if report_type in ('sales_invoice', 'sales_return'):
            inv_type = 'sales_return' if (is_negative or is_cn_title or report_type == 'sales_return') else 'sales_invoice'
        else:
            inv_type = 'purchase_return' if (is_negative or is_cn_title or report_type == 'purchase_return') else 'purchase_invoice'

        # Ensure values are negative for returns
        if inv_type in ('sales_return', 'purchase_return'):
            if parsed.get('total_amount', 0.0) > 0.0:
                parsed['total_amount'] = -parsed['total_amount']
            if parsed.get('vat_amount', 0.0) > 0.0:
                parsed['vat_amount'] = -parsed['vat_amount']
            if parsed.get('total_including_vat', 0.0) > 0.0:
                parsed['total_including_vat'] = -parsed['total_including_vat']

        # ── Determine if the API data was too incomplete to be reliable ──
        # Flag the line so users can spot and fix it easily in the list view.
        missing_invoice_number = not parsed.get('invoice_number')
        missing_supplier       = not parsed.get('supplier')
        missing_date           = not parsed.get('date')
        zero_amounts           = (
            (parsed.get('total_amount') or 0.0) == 0.0 and
            (parsed.get('vat_amount') or 0.0) == 0.0 and
            (parsed.get('total_including_vat') or 0.0) == 0.0
        )
        # amounts_derived: API could not read some amounts directly — system had to
        # calculate/guess them (e.g. net value derived from gross, inconsistent totals)
        amounts_derived = parsed.pop('amounts_derived', False)

        # Warn when critical fields the API should read are missing/unreadable:
        #   - date could not be read, OR
        #   - invoice number could not be read, OR
        #   - supplier name could not be read, OR
        #   - all monetary amounts are zero (API returned no amounts at all)
        # NOTE: amounts_derived is intentionally NOT included here — many valid bills
        # (e.g. zero-VAT invoices) trigger derived calculations even when data is correct.
        parse_warning = (missing_date or missing_invoice_number or missing_supplier
                         or zero_amounts)
        if parse_warning:
            _logger.warning(
                'VAT Reporting: line created with parse warning — '
                'missing_date=%s missing_inv_no=%s missing_supplier=%s '
                'zero_amounts=%s amounts_derived=%s',
                missing_date, missing_invoice_number, missing_supplier,
                zero_amounts, amounts_derived)

        return self.create({
            'report_id':     report_id,
            'job_id':        job_id,
            'raw_data':      json.dumps(entry, indent=2, default=str),
            'invoice_type':  inv_type,
            'parse_warning': parse_warning,
            **parsed,
        })