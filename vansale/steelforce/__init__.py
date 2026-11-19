"""Steel Force adapter: how the app works next to the `sf_trading` app.

Branch `develop_2` only. sf_trading owns Steel Force's business rules (branch,
minimum price, credit, customer approval, return reasons, ...). This module
never re-implements one: it fills the fields those rules read and uses
sf_trading's own functions where they exist.

Every function here is safe on a site without sf_trading: it checks for the
field / app it needs and otherwise leaves the standard behaviour alone. The
standard modules call in at a few points only, so merging `develop` into
`develop_2` stays easy.
"""

from __future__ import annotations

from typing import Optional

import frappe

SF_APP = "sf_trading"


def is_active() -> bool:
    """sf_trading is installed on this site."""
    return SF_APP in frappe.get_installed_apps()


# ─── Payment mode on the document ─────────────────────────────────────────────

_PAYMENT_MODE_FIELD = "custom_payment_mode"


def set_payment_mode(doc, pay_type: Optional[str]) -> None:
    """sf_trading's `custom_payment_mode` (Cash / Credit / Cheque) on a Sales
    Invoice / Sales Order. The field defaults to its first option (Cash) when
    nothing is sent, so a credit sale must say Credit explicitly; sf_trading's
    credit, cash-limit and due-date rules all read it."""
    if not doc.meta.has_field(_PAYMENT_MODE_FIELD):
        return
    value = {"cash": "Cash", "credit": "Credit", "cheque": "Cheque"}.get((pay_type or "").lower())
    if value:
        doc.set(_PAYMENT_MODE_FIELD, value)


def payment_type_of(doc) -> Optional[str]:
    """"cash" / "credit" / "cheque" from `custom_payment_mode`, or None when the
    site has no such field (the caller then derives it the standard way)."""
    if not doc.meta.has_field(_PAYMENT_MODE_FIELD) or not doc.get(_PAYMENT_MODE_FIELD):
        return None
    return {"Cash": "cash", "Cheque": "cheque"}.get(doc.get(_PAYMENT_MODE_FIELD), "credit")


# ─── New customers ────────────────────────────────────────────────────────────

def on_new_customer(doc, company: Optional[str] = None) -> None:
    """sf_trading shows a branch user only the customers of their company
    (`custom_company`); the desk fills it in the browser, so an API-created
    customer must carry it or it disappears from the salesman's lists."""
    if doc.meta.has_field("custom_company") and not doc.get("custom_company"):
        from vansale.api.invoice import _user_company

        doc.custom_company = company or _user_company()


# The desk's Create Customer dialog lets only these make a B2B customer
# (sf_trading/public/js/create_customer.js); Administrator too.
_B2B_CREATOR_ROLES = {"B2B Creator", "System Manager"}


def can_create_b2b(user: Optional[str] = None) -> bool:
    """Steel Force: only a B2B Creator makes a B2B (company) customer, as on
    the desk. Elsewhere everyone may."""
    if not is_active():
        return True
    user = user or frappe.session.user
    return user == "Administrator" or bool(set(frappe.get_roles(user)) & _B2B_CREATOR_ROLES)


def check_new_customer(
    customer_name: str, is_b2b: bool, mobile_no: Optional[str], tax_id: Optional[str] = None, has_document: bool = False
) -> None:
    """The rules sf_trading keeps in its Create Customer dialog rather than on
    the Customer itself (sf_trading/api/customer.py), so an app-made customer
    meets them too. Nothing elsewhere."""
    if not is_active():
        return
    from frappe import _

    if is_b2b and not can_create_b2b():
        frappe.throw(_("Only a B2B Creator can create a B2B customer."))
    if not (mobile_no or "").strip():
        frappe.throw(_("Mobile No is required"))
    # sf_trading bills a VAT customer only with its certificate on file.
    if (tax_id or "").strip() and not has_document:
        frappe.throw(_("Add a photo of the CR / VAT certificate."))
    # The name sf_trading saves is in Title Case; the lookup ignores case.
    if frappe.db.exists("Customer", {"customer_name": customer_name.strip()}):
        frappe.throw(_("Customer '{0}' already exists.").format(customer_name.strip()))


def link_vat_document(customer: str, file_url: Optional[str]) -> None:
    """Steel Force: the photo taken with a VAT number is the customer's VAT
    Certificate, filed in the Supporting Documents row sf_trading adds for the
    number (the desk's dialog files its upload the same way); sf_trading's
    customer approval looks for the file there."""
    if not is_active() or not file_url:
        return
    try:
        from sf_trading.party_documents import TABLE, VAT_DOCUMENT_TYPE
    except ImportError:
        return
    field = frappe.get_meta("Customer").get_field(TABLE)
    if not field:
        return
    row = frappe.db.get_value(
        field.options,
        {
            "parent": customer,
            "parenttype": "Customer",
            "parentfield": TABLE,
            "document_type": VAT_DOCUMENT_TYPE,
            "attachment": ["is", "not set"],
        },
        "name",
        order_by="idx asc",
    )
    if row:
        frappe.db.set_value(field.options, row, "attachment", file_url, update_modified=False)


# ─── Return reasons ───────────────────────────────────────────────────────────

_REASON_TEMPLATE_FIELD = "custom_return_reason_template"
_REASON_DOCTYPE = "Sales Return Reason"


def _uses_reason_master() -> bool:
    return bool(
        frappe.get_meta("Sales Invoice").has_field(_REASON_TEMPLATE_FIELD)
        and frappe.db.exists("DocType", _REASON_DOCTYPE)
    )


def return_reason_options() -> list[str]:
    """The reasons a salesman picks from: sf_trading's *Sales Return Reason*
    list on its sites, else the app's own list."""
    if _uses_reason_master():
        names = frappe.get_all(_REASON_DOCTYPE, pluck="name", order_by="name asc")
        if names:
            # "Other" last, as in the app's own list
            return [n for n in names if n != "Other"] + (["Other"] if "Other" in names else [])
    from vansale.api.sales_return import RETURN_REASONS

    return list(RETURN_REASONS)


def set_return_reason(doc, reason_option: str, reason_text: str, note: Optional[str]) -> bool:
    """Write the reason the sf_trading way (template link + free text).
    Returns False when the site doesn't use the reason master, so the caller
    keeps the standard behaviour."""
    if not _uses_reason_master():
        return False
    if frappe.db.exists(_REASON_DOCTYPE, reason_option):
        doc.set(_REASON_TEMPLATE_FIELD, reason_option)
    elif frappe.db.exists(_REASON_DOCTYPE, "Other"):
        doc.set(_REASON_TEMPLATE_FIELD, "Other")
    extra = (note or "").strip()
    detail = extra or (reason_text if reason_text != reason_option else "")
    if detail and doc.meta.get_field("custom_return_reason") and doc.meta.get_field(
        "custom_return_reason"
    ).fieldtype in ("Data", "Small Text", "Text"):
        doc.custom_return_reason = detail
    return True


def copy_to_return(doc, original) -> None:
    """A credit note keeps the original sale's sales person (targets and
    commission net off against it) and payment mode (sf_trading treats a cash
    return and a credit return differently)."""
    for field in ("custom_sales_person", _PAYMENT_MODE_FIELD):
        if doc.meta.has_field(field) and original.get(field) and not doc.get(field):
            doc.set(field, original.get(field))


# ─── Quotation → Sales Invoice ────────────────────────────────────────────────

def invoice_from_quotation(quotation_name: str, customer: str):
    """Unsaved Sales Invoice for a submitted quotation.

    Steel Force: a customer's quotation goes through sf_trading's own mapping
    (the desk's "Sales Invoice" button). sf_trading has no lead quotations, and
    its mapping can't take one (it bills the party, i.e. the lead), so a
    lead's quotation goes through ERPNext's mapping and gets sf_trading's
    row link (`custom_quotation`) stamped on, which is what drives the
    quotation's status and the one-invoice-per-quotation check.
    Elsewhere: ERPNext's mapping. `customer` is the quotation's customer, or
    the customer its lead was just converted into.
    """
    from erpnext.selling.doctype.quotation.quotation import make_sales_invoice

    linked = is_active() and frappe.get_meta("Sales Invoice Item").has_field("custom_quotation")
    if not linked:
        return make_sales_invoice(quotation_name)

    if frappe.db.get_value("Quotation", quotation_name, "quotation_to") == "Customer":
        from sf_trading.api.quotation import make_sales_invoice_from_quotation

        return frappe.get_doc(make_sales_invoice_from_quotation(quotation_name))

    existing = invoices_for_quotation(quotation_name)
    if existing:
        frappe.throw(
            frappe._("A Sales Invoice {0} already exists for Quotation {1}.").format(
                frappe.bold(existing[0]), quotation_name
            ),
            title=frappe._("Duplicate Invoice"),
        )
    invoice = make_sales_invoice(quotation_name)
    if invoice.customer != customer:
        invoice.customer = customer
        invoice.run_method("set_missing_values")
    for row in invoice.items:
        row.custom_quotation = quotation_name
    return invoice


def invoices_for_quotation(quotation_name: str) -> list[str]:
    """Sales Invoices made straight from a quotation (sf_trading links their
    rows through `custom_quotation`); [] on sites without that link."""
    if not frappe.get_meta("Sales Invoice Item").has_field("custom_quotation"):
        return []
    return frappe.get_all(
        "Sales Invoice Item",
        filters={"custom_quotation": quotation_name, "docstatus": ["<", 2]},
        pluck="parent",
        distinct=True,
    )


def sale_history_conditions() -> Optional[tuple[list, dict, Optional[str]]]:
    """Which past sales a salesman sees, as the desk's Last Selling Rate /
    Customer Last Selling Rate dialogs: the document's cost centre (the
    branch) only, within sf_trading's permitted companies / cost centres
    (aliases si / sii). Returns (where, params, cost centre), or None where
    sf_trading isn't installed."""
    if not is_active():
        return None
    try:
        from sf_trading.api.last_selling_rate import _permission_conditions
    except ImportError:
        return None
    where, params = _permission_conditions()
    where = list(where)
    params = {k: tuple(v) if isinstance(v, list) else v for k, v in params.items()}
    from vansale.api.invoice import _user_default
    from vansale.api.me import van_default

    cost_center = van_default("Cost Center") or _user_default("Cost Center")
    if cost_center:
        where.append("(sii.cost_center = %(branch_cost_center)s OR si.cost_center = %(branch_cost_center)s)")
        params["branch_cost_center"] = cost_center
    return where, params, cost_center


def warehouse_stock(item_code: str, company: str, own: Optional[str]) -> Optional[list[dict]]:
    """Stock per warehouse as sf_trading's Stock Availability shows it, or None
    where it isn't installed."""
    if not is_active():
        return None
    try:
        from sf_trading.api.warehouse_stock import get_item_warehouse_stock
    except ImportError:
        return None
    rows = get_item_warehouse_stock(item_code, company=company, target_warehouse=own) or []
    return [
        {"warehouse": r["warehouse"], "warehouse_name": r.get("warehouse_name") or r["warehouse"], "qty": frappe.utils.flt(r.get("stock_qty"))}
        for r in rows
    ]


def draft_sale_printable() -> bool:
    """sf_trading refuses to print a draft Sales Invoice (a draft return still
    prints), so the app hides Print on draft sales there."""
    if not is_active():
        return True
    try:
        from sf_trading import draft_print  # noqa: F401
    except ImportError:
        return True
    return "sf_trading.draft_print.block_draft_sale_print" not in str(
        frappe.get_hooks("doc_events").get("Sales Invoice", {}).get("before_print", "")
    )


# ─── Minimum selling price ────────────────────────────────────────────────────

def min_rate(item_code: str, uom_cf: float, price_list: Optional[str], warehouse: Optional[str] = None,
             branch: Optional[str] = None) -> Optional[float]:
    """sf_trading's minimum rate for one unit of `uom_cf` stock units (offer price,
    else the list price and cost + Item Group margin, whichever is higher), in
    company currency. None on sites without the rule, or when the price list is
    in another currency (the app then leaves the check to the server)."""
    if not is_active():
        return None
    try:
        from sf_trading.api.selling_price_validation import get_min_selling_price
    except ImportError:
        return None
    if price_list:
        from vansale.api.invoice import _user_company

        pl_currency = frappe.db.get_value("Price List", price_list, "currency")
        company = _user_company()
        if pl_currency and company and pl_currency != frappe.get_cached_value("Company", company, "default_currency"):
            return None
    result = get_min_selling_price(
        item_code, warehouse=warehouse, price_list=price_list, uom_cf=uom_cf or 1.0, branch=branch
    ) or {}
    value = float(result.get("min_price") or 0)
    return value or None


# ─── Customer status and pre-check ────────────────────────────────────────────

def credit_extras(customer: str, company: str) -> dict:
    """Steel Force additions to the customer's credit status
    (`vansale.api.customer.credit_status`); {} elsewhere:

    cash_exempt       a Cash sale never counts against the credit limit here
    blocking_overdue  the oldest credit invoice past the customer's credit days:
                      sf_trading refuses any new Credit sale or order until it is paid
    approval          master approval of the customer (an unapproved, covered
                      customer cannot be sold to at all, cash included)
    branch            the customer's own credit sub-limit at the van's branch, if set
    """
    if not is_active() or not customer:
        return {}
    from vansale.api.me import van_default

    out: dict = {"cash_exempt": True, "blocking_overdue": None, "approval": None, "branch": None}

    try:
        from sf_trading.api.sales_invoice_override import _get_overdue_invoice

        overdue = _get_overdue_invoice(customer, company)
    except ImportError:
        overdue = None
    if overdue:
        out["blocking_overdue"] = {
            "name": overdue.get("name"),
            "posting_date": str(overdue.get("posting_date")),
            "outstanding_amount": float(overdue.get("outstanding_amount") or 0),
        }

    try:
        from sf_trading.master_approval import get_approval_state

        approval = get_approval_state("Customer", customer) or {}
    except Exception:
        approval = {}
    if approval.get("enabled"):
        out["approval"] = {
            "covered": bool(approval.get("covered")),
            "status": approval.get("status") or "",
            "approved": bool(approval.get("approved")),
            "missing": approval.get("missing") or [],
        }

    branch = van_default("Branch")
    try:
        from sf_trading.credit_limit import branch_credit_exposure, branch_sub_limit
    except ImportError:
        branch_sub_limit = None
    if branch and branch_sub_limit:
        limit = float(branch_sub_limit(customer, branch) or 0)
        if limit:
            used = float(branch_credit_exposure(customer, branch) or 0)
            out["branch"] = {"name": branch, "limit": limit, "used": used, "available": limit - used}
    return out


_SF_PAYMENT_MODE = {"cash": "Cash", "credit": "Credit", "cheque": "Cheque"}


def precheck(
    doctype: str, customer: str, payment_type: Optional[str], lines: list[dict], amount: float = 0
) -> dict:
    """sf_trading's own refusals for a sale that is about to be submitted,
    run without saving anything: customer gates (contact, credit documents,
    approval), an overdue credit invoice for a credit sale, and rates below
    the minimum. {"problems": [...], "warnings": [...]}."""
    out: dict = {"problems": [], "warnings": []}
    if not is_active() or not customer:
        return out
    from vansale.api.invoice import _user_company
    from vansale.api.me import van_default

    company = _user_company()
    mode = _SF_PAYMENT_MODE.get((payment_type or "").lower())
    if doctype in ("Sales Invoice", "Sales Order"):
        from sf_trading.party_alert import get_party_alert

        header = {"doctype": doctype, "customer": customer, "company": company, "__islocal": 1}
        if mode:
            header["custom_payment_mode"] = mode
        alert = get_party_alert(doctype, frappe.as_json(header)) or {}
        out["problems"].extend(_plain(p) for p in alert.get("problems") or [])
        out["warnings"].extend(_plain(h) for h in alert.get("hints") or [])

    # Credit and cheque count against the limits (sf_trading.credit_limit).
    extras = credit_extras(customer, company) if mode in ("Credit", "Cheque") else {}
    sub = extras.get("branch")
    if sub and amount and doctype in ("Sales Invoice", "Sales Order") and sub["used"] + amount > sub["limit"]:
        out["problems"].append(
            frappe._("Over the branch credit limit at {0}: {1} used of {2}, this sale adds {3}.").format(
                sub["name"], round(sub["used"], 2), round(sub["limit"], 2), round(amount, 2)
            )
        )
    # sf_trading refuses only a Credit sale / order over an overdue invoice (not a cheque).
    if mode == "Credit" and doctype in ("Sales Invoice", "Sales Order"):
        overdue = extras.get("blocking_overdue")
        if overdue:
            out["problems"].append(
                frappe._("Credit sale refused: invoice {0} of {1} is overdue ({2} outstanding).").format(
                    overdue["name"], overdue["posting_date"], overdue["outstanding_amount"]
                )
            )

    warehouse = van_default("Warehouse")
    branch = van_default("Branch")
    price_list = lines[0].get("price_list") if lines else None
    from vansale.api.me import current_user_van_price_list

    price_list = price_list or current_user_van_price_list() or frappe.db.get_single_value(
        "Selling Settings", "selling_price_list"
    )
    for line in lines or []:
        floor = min_rate(line.get("item_code"), float(line.get("conversion_factor") or 1), price_list, warehouse, branch)
        rate = float(line.get("rate") or 0)
        if floor and rate + 0.0001 < floor:
            out["problems"].append(
                frappe._("{0}: rate {1} is below the minimum {2}.").format(
                    line.get("item_name") or line.get("item_code"), rate, round(floor, 2)
                )
            )
    return out


def _plain(text) -> str:
    """Server messages carry HTML (bold, line breaks); the app shows text."""
    import re

    return re.sub(r"<[^>]+>", "", str(text or "")).strip()


# ─── Payment modes ────────────────────────────────────────────────────────────

def branch_payment_modes(company: str, is_return: int = 0, is_pdc: int = 0) -> Optional[list[str]]:
    """The modes sf_trading allows on the salesman's branch (cash/bank, or the
    post-dated cheque modes), or None on sites without that rule."""
    if not is_active():
        return None
    try:
        from sf_trading.api.sales_invoice_payment import get_payment_modes_with_account
    except ImportError:
        return None
    from vansale.api.me import van_default

    return get_payment_modes_with_account(company, is_return=is_return, is_pdc=is_pdc, branch=van_default("Branch"))



# ─── Collection on submit (cash collected now, cheques) ───────────────────────

def cheque_modes() -> list[str]:
    """The branch's post-dated cheque modes (Branch Configuration "For PDC");
    [] where there are none or no sf_trading."""
    from vansale.api.invoice import _user_company

    return branch_payment_modes(_user_company(), is_pdc=1) or []


def collect_invoice(inv, rows: list[dict], entry_status: str) -> Optional[list[str]]:
    """Payment Entries for a submitted sale the way the Steel Force desk makes
    them: sf_trading's `create_pos_payments_for_invoice` (one entry per mode,
    cheque number / date for PDC, its write-off and branch rules). Used when the
    entries are to be submitted at once (sf_trading always submits); returns
    None to leave the standard path (draft entries, other sites)."""
    if not rows or not is_active():
        return None
    is_cheque = inv.get(_PAYMENT_MODE_FIELD) == "Cheque"
    if entry_status != "Submit" and not is_cheque:
        return None
    try:
        from sf_trading.api.sales_invoice_payment import create_pos_payments_for_invoice
    except ImportError:
        return None
    remaining = float(inv.outstanding_amount or 0)
    payments = []
    for row in rows:
        amount = min(float(row["amount"]) if row.get("amount") is not None else remaining, remaining)
        if amount <= 0:
            continue
        payments.append({"mode_of_payment": row["mode_of_payment"], "amount": amount})
        remaining -= amount
    if not payments:
        return []
    first = rows[0]
    names = create_pos_payments_for_invoice(
        inv.name,
        payments,
        cheque_date=first.get("reference_date") if is_cheque else None,
        cheque_no=first.get("reference_no") if is_cheque else None,
        posting_date=str(inv.posting_date),
    )
    return list(names or [])



# ─── Driver (delivery person) ─────────────────────────────────────────────────

_DRIVER_FIELD = "custom_driver"


def has_driver_field() -> bool:
    return is_active() and frappe.get_meta("Sales Invoice").has_field(_DRIVER_FIELD)


def driver_of(doc) -> Optional[str]:
    """The delivery person on this document, or None."""
    if not doc.meta.has_field(_DRIVER_FIELD):
        return None
    return doc.get(_DRIVER_FIELD) or None


def driver_name(driver: Optional[str]) -> Optional[str]:
    if not driver:
        return None
    return frappe.db.get_value("Driver", driver, "full_name") or driver


def set_driver(doc, driver: Optional[str], pay_type: Optional[str]) -> None:
    """The delivery person on a cash sale (sf_trading checks the driver's
    overdue collections and cash limit, and clears it on non-cash sales)."""
    if not doc.meta.has_field(_DRIVER_FIELD):
        return
    if (pay_type or "").lower() != "cash":
        doc.set(_DRIVER_FIELD, None)
    elif driver is not None:
        doc.set(_DRIVER_FIELD, driver or None)



def has_order_payment_mode() -> bool:
    """Sales Orders carry a Cash / Credit payment mode on this site (sf_trading)."""
    return frappe.get_meta("Sales Order").has_field(_PAYMENT_MODE_FIELD)
