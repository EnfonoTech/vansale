"""Pure builders for the short summary shown on the Approvals detail screen.
No `frappe` import: callers pass duck-typed field objects (anything with
`fieldname`, `fieldtype`, ... attributes, such as a `DocField` or a
`SimpleNamespace`) and plain dicts, so nothing here touches a site.

The field choice mirrors the desk's own approval preview (Permission Manager,
`approval_inbox.js`, `_load_preview`): the same skipped types and names, the
same order. Field labels, column headers and the words "Yes"/"No" go through
the optional `translate` callable (the caller passes `frappe._`); without it
they are the English source strings.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Callable, Optional

Translate = Callable[[str], str]


def _same(text: str) -> str:
    return text


PARTY_FIELDS = (
    "customer_name",
    "supplier_name",
    "party_name",
    "party",
    "customer",
    "supplier",
    "title",
)
"""Who the document is with, best first; the first one the doctype has wins."""

AMOUNT_FIELDS = (
    "grand_total",
    "rounded_total",
    "total_debit",
    "paid_amount",
    "amount",
    "total_amount",
)
"""What the document is worth, best first; the first one the doctype has wins."""

SKIP_TYPES = frozenset(
    {
        "Section Break", "Column Break", "HTML", "Button", "Tab Break", "Code",
        "JSON", "Long Text", "Small Text", "Text", "Text Editor", "Signature",
        "Attach", "Attach Image", "Barcode", "Geolocation", "Table",
        "Table MultiSelect", "Password",
    }
)  # fmt: skip
"""Field types that are never a key fact: layout, long text, files, tables."""

SKIP_NAMES = frozenset(
    {
        "exchange_rate", "conversion_rate", "base_exchange_rate",
        "naming_series", "amended_from", "amended_to", "docstatus", "idx",
        "owner", "modified", "modified_by", "creation", "name",
        "workflow_state", "letter_head", "select_print_heading", "tc_name",
        "terms", "taxes_and_charges", "shipping_rule", "discount_amount",
        "additional_discount_percentage", "apply_discount_on", "in_words",
        "base_in_words", "language", "meta_image", "status_field", "source",
        "base_grand_total", "base_net_total", "base_total",
        "base_tax_withholding_net_total", "outstanding_amount", "debit_to",
        "credit_to", "against_expense_account", "against_income_account",
        "remarks", "user_remark", "instructions", "total_advance",
        "total_taxes_and_charges", "total_billing_amount", "update_stock",
        "set_warehouse", "set_target_warehouse", "scan_barcode", "barcode",
        "image", "company_address_display", "customer_address",
        "contact_display", "contact_email", "contact_mobile",
        "shipping_address_name", "billing_address",
    }
)  # fmt: skip
"""Technical field names that are never a key fact."""

_ITEM_COLUMNS = [("item_name", "Item"), ("qty", "Qty"), ("amount", "Amount")]

LINE_TABLES: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "Journal Entry": (
        "accounts",
        [
            ("account", "Account"),
            ("debit_in_account_currency", "Debit"),
            ("credit_in_account_currency", "Credit"),
        ],
    ),
    "Purchase Invoice": ("items", _ITEM_COLUMNS),
    "Purchase Order": ("items", _ITEM_COLUMNS),
    "Sales Invoice": ("items", _ITEM_COLUMNS),
    "Sales Order": ("items", _ITEM_COLUMNS),
    "Quotation": ("items", _ITEM_COLUMNS),
    "Payment Entry": (
        "references",
        [
            ("reference_doctype", "Type"),
            ("reference_name", "Reference"),
            ("allocated_amount", "Allocated"),
        ],
    ),
    "Stock Reconciliation": (
        "items",
        [
            ("item_code", "Item"),
            ("qty", "Qty"),
            ("valuation_rate", "Rate"),
        ],
    ),
}
"""Per doctype: the child table to preview and its `(fieldname, header)`
columns."""

_NUMBER_TYPES = ("Currency", "Float", "Percent")


def pick_party_amount(
    has_field: Callable[[str], bool],
) -> tuple[Optional[str], Optional[str]]:
    """The fieldnames that name the party and the amount of a doctype, as
    `(party_field, amount_field)`; either is None when the doctype has none
    of the candidates. `has_field` answers whether the doctype has a field."""
    party = next((name for name in PARTY_FIELDS if has_field(name)), None)
    amount = next((name for name in AMOUNT_FIELDS if has_field(name)), None)
    return party, amount


def format_value(
    fieldtype: str, value, precision: int, *, translate: Translate = _same
) -> Optional[str]:
    """How a field value reads on the summary, or None when it cannot be shown
    as text (a table or any other dict/list, or no value at all).

    Check is Yes/No (through `translate`); Currency, Float and Percent are
    grouped by thousands with `precision` decimals (rounded half up); Int is
    plain; Date is an ISO date and Datetime an ISO date-time to the second;
    the rest is the string itself.
    """
    if value is None or isinstance(value, (dict, list)):
        return None
    if fieldtype == "Check":
        return translate("Yes") if _is_checked(value) else translate("No")
    if fieldtype in _NUMBER_TYPES:
        return _grouped(value, precision)
    if fieldtype == "Int":
        try:
            return str(int(value))
        except (TypeError, ValueError):
            return str(value)
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if fieldtype in ("Date", "Datetime") and hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def key_facts(
    fields: list, doc: dict, precision: int, limit: int = 8, *, translate: Translate = _same
) -> list[dict]:
    """Up to `limit` `{"label", "value"}` facts to show for a document.

    Same rule as the desk preview: a field is a candidate when its type and
    name are not in the skip lists, it is neither hidden nor print-hidden and
    the document has a value for it (0 counts, None and "" do not). Fields
    marked `in_preview` come first, then `bold`, then `in_list_view`, then the
    rest, each group in field order. A value that cannot be shown as text is
    dropped and does not use up a slot. Labels go through `translate`.
    """
    candidates = [field for field in fields if _is_candidate(field, doc)]
    candidates.sort(key=_rank)

    facts: list[dict] = []
    for field in candidates:
        if len(facts) >= limit:
            break
        fieldname = field.fieldname
        fieldtype = getattr(field, "fieldtype", None)
        value = format_value(fieldtype, doc[fieldname], precision, translate=translate)
        if value is None:
            continue
        label = getattr(field, "label", None) or fieldname
        facts.append({"label": translate(label), "value": value})
    return facts


def first_lines(
    doctype: str, doc: dict, precision: int, limit: int = 3, *, translate: Translate = _same
) -> dict:
    """The first `limit` lines of the document's main child table, as
    `{"columns": [header], "rows": [[cell]], "total": n}` where `total` is the
    number of lines the document has. Headers go through `translate`. Numbers
    are shown with `precision` decimals, except a quantity (`qty`), which
    shows only the decimals it has; text is shown as is, a missing value as
    "". A doctype with no entry in `LINE_TABLES`, or a document with no lines,
    gives the empty shape.
    """
    empty = {"columns": [], "rows": [], "total": 0}
    if doctype not in LINE_TABLES:
        return empty
    table, columns = LINE_TABLES[doctype]
    lines = doc.get(table) or []
    if not lines:
        return empty

    return {
        "columns": [translate(header) for _fieldname, header in columns],
        "rows": [
            [_cell(fieldname, line.get(fieldname), precision) for fieldname, _header in columns]
            for line in lines[:limit]
        ],
        "total": len(lines),
    }


def _is_checked(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "yes", "true")
    return bool(value)


def _grouped(value, precision: int) -> str:
    """`value` with thousands separators and `precision` decimals, half up."""
    places = max(precision or 0, 0)
    try:
        rounded = Decimal(str(value)).quantize(
            Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP
        )
    except (InvalidOperation, ValueError):
        return str(value)
    if not rounded:
        rounded = abs(rounded)  # -0.0001 reads "0.00", not "-0.00"
    return f"{rounded:,.{places}f}"


def _quantity(value) -> str:
    """A quantity grouped by thousands with only the decimals it has:
    2 -> "2", 2.5 -> "2.5", 1200 -> "1,200"."""
    try:
        number = Decimal(str(value)).normalize()
    except (InvalidOperation, ValueError):
        return str(value)
    if not number:
        number = abs(number)
    return f"{number:,f}"


def _cell(fieldname: str, value, precision: int) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        if fieldname == "qty":
            return _quantity(value)
        return _grouped(value, precision)
    return str(value)


def _is_candidate(field, doc: dict) -> bool:
    fieldname = getattr(field, "fieldname", None)
    return (
        getattr(field, "fieldtype", None) not in SKIP_TYPES
        and fieldname not in SKIP_NAMES
        and not getattr(field, "hidden", 0)
        and not getattr(field, "print_hide", 0)
        and doc.get(fieldname) not in (None, "")
    )


def _rank(field) -> int:
    if getattr(field, "in_preview", 0):
        return 0
    if getattr(field, "bold", 0):
        return 1
    if getattr(field, "in_list_view", 0):
        return 2
    return 3
