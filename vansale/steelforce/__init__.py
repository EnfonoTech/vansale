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

        doc.custom_company = company or _user_company(throw=True)


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


def mobile_min_digits(company: Optional[str]) -> int:
    """Steel Force: a Saudi company's customer needs a mobile of at least 10
    digits (sf_trading's party_master_rules; a Bahrain company's does not).
    0 = no length rule."""
    if not is_active() or not company:
        return 0
    try:
        from sf_trading.party_master_rules import is_saudi
    except ImportError:
        return 0
    return 10 if is_saudi(company) else 0


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


def _sees_every_item() -> bool:
    user = frappe.session.user
    return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def company_items(company: Optional[str]) -> Optional[set]:
    """Steel Force: the items of `company` (an Item Default row for it), the
    ones sf_trading shows a branch user; None = no limit (other sites, a
    System Manager)."""
    if not is_active() or not company or _sees_every_item():
        return None
    try:
        from sf_trading.company_items import item_codes_for_companies
    except ImportError:
        return None
    return set(item_codes_for_companies([company]))


def item_in_company(item_code: str, company: Optional[str]) -> bool:
    """Steel Force: the item belongs to `company` (see company_items)."""
    if not is_active() or not company or _sees_every_item():
        return True
    if frappe.db.exists("Item Default", {"parent": item_code, "parenttype": "Item", "company": company}):
        return True
    return bool(frappe.db.get_value("Item", item_code, "is_fixed_asset"))


def branch_selling_list(price_list: Optional[str]) -> Optional[str]:
    """Steel Force: the selling price list a document of the van's branch is
    priced from. sf_trading allows only the branch's own lists (Branch
    Configuration) and refuses any other on save, so a list outside that set
    is replaced by the branch's default, as its form does. Unchanged
    elsewhere, or where the branch names no lists."""
    if not is_active():
        return price_list
    from vansale.api.me import van_default

    branch = van_default("Branch")
    if not branch:
        return price_list
    try:
        from sf_trading.branch_price_list import allowed_price_lists, default_price_list
    except ImportError:
        return price_list
    allowed = allowed_price_lists(branch, "selling")
    if not allowed or price_list in allowed:
        return price_list
    return default_price_list(branch, "selling") or price_list


def row_price_lists() -> list[str]:
    """Steel Force: the selling price lists a line may name for itself (an
    offer list next to the branch's default, sf_trading's per-row Price List,
    `custom_price_list` on Quotation / Sales Order / Sales Invoice items).
    The branch's own lists, when it has more than one; else none."""
    if not is_active() or not frappe.get_meta("Sales Invoice Item").has_field("custom_price_list"):
        return []
    from vansale.api.me import van_default

    branch = van_default("Branch")
    if not branch:
        return []
    try:
        from sf_trading.branch_price_list import allowed_price_lists, default_price_list
    except ImportError:
        return []
    allowed = list(allowed_price_lists(branch, "selling") or [])
    if len(allowed) < 2:
        return []
    default = default_price_list(branch, "selling")
    return sorted(allowed, key=lambda name: (name != default, name))


def row_price_list(price_list: Optional[str]) -> Optional[str]:
    """A line's own price list, checked: one of `row_price_lists()`, else refused."""
    price_list = (price_list or "").strip()
    if not price_list:
        return None
    if price_list not in row_price_lists():
        frappe.throw(frappe._("Price list {0} is not one of your branch's lists").format(price_list))
    return price_list


def branch_prices(rows: list, name_of=lambda row: row[0]) -> list:
    """Steel Force: Item Price rows as a document of the van's branch sees
    them (sf_trading's `visible`): prices limited to other branches dropped,
    the branch's own ahead of the general ones. Unchanged elsewhere."""
    if not is_active() or not rows:
        return rows
    try:
        from sf_trading.item_price_branch import table_ready, visible
    except ImportError:
        return rows
    if not table_ready():
        return rows
    from vansale.api.me import van_default

    return visible(rows, van_default("Branch"), name_of=name_of)


def company_print_format(company: Optional[str], doctype: str) -> Optional[str]:
    """Steel Force: the print format the company's desk prints `doctype` with
    (Company > Print Formats, sf_trading), when set and enabled; None else."""
    if not is_active() or not company or not frappe.db.table_exists("Company Print Format"):
        return None
    fmt = frappe.db.get_value(
        "Company Print Format",
        {"parent": company, "parenttype": "Company", "document_type": doctype},
        "print_format",
    )
    if fmt and not frappe.db.get_value("Print Format", fmt, "disabled"):
        return fmt
    return None


def return_needs_approval(doc) -> bool:
    """Steel Force: a return sf_trading lets through only by its approval chain
    (Return Approval on, and over the limit when limited by amount)."""
    if not is_active():
        return False
    try:
        from sf_trading.sales_return import needs_approval
    except ImportError:
        return False
    return bool(needs_approval(doc))


def plan_refund(doc, refund: Optional[dict]) -> None:
    """Steel Force: a return waiting for approval cannot be paid yet (ERPNext
    refuses a Payment Entry against a draft), so the refund the salesman
    agreed is kept on the return as sf_trading's plan, and paid when the
    approval submits it — as the desk does."""
    if not refund or not refund.get("mode_of_payment"):
        return
    from frappe import _
    from frappe.utils import flt
    from sf_trading.planned_payment import refundable_amount, set_planned_payments

    mode = refund["mode_of_payment"]
    allowed = branch_payment_modes(doc.company, is_return=1)
    if allowed is not None and mode not in allowed:
        frappe.throw(_("Mode of Payment {0} is not used for refunds at your branch").format(mode))
    amount = flt(refund.get("amount")) or flt(refundable_amount(doc))
    set_planned_payments(doc.name, [{"mode_of_payment": mode, "amount": amount}])
    doc.reload()


def return_window(invoice) -> Optional[dict]:
    """Steel Force's return window for a submitted sale (sf_trading's own
    `window_state`): {blocked, past_window, days, age, can_override}, or None
    where there is no window (other sites, the switch off, a return)."""
    if not is_active() or invoice.get("is_return") or int(invoice.get("docstatus") or 0) != 1:
        return None
    try:
        from sf_trading.sales_return import window_enabled, window_state
    except ImportError:
        return None
    try:
        if not window_enabled():
            return None
        state = window_state("Sales Invoice", invoice.name)
    except Exception:
        frappe.log_error(title="vansale: return window")
        return None
    return {k: state.get(k) for k in ("blocked", "past_window", "days", "age", "can_override")}


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
    doctype: str, customer: str, payment_type: Optional[str], lines: list[dict], amount: float = 0, is_return: int = 0
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
        if is_return:
            # sf_trading's gates read it: some let a return through, the
            # credit-documents and phone gates do not.
            header["is_return"] = 1
        alert = get_party_alert(doctype, frappe.as_json(header)) or {}
        out["problems"].extend(_plain(p) for p in alert.get("problems") or [])
        out["warnings"].extend(_plain(h) for h in alert.get("hints") or [])
    if is_return:
        # A return uses no credit and is not priced against the minimum.
        return out
    if doctype == "Sales Order":
        limit = _order_limit_refusal(customer, company, mode)
        if limit:
            out["problems"].append(limit)

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
    from vansale.api.me import current_user_van_price_list

    price_list = branch_selling_list(
        current_user_van_price_list() or frappe.db.get_single_value("Selling Settings", "selling_price_list")
    )
    row_lists = set(row_price_lists())
    for line in lines or []:
        # A line priced from its own list (an offer list) is held to that list's minimum.
        own = line.get("price_list")
        line_list = own if own and own in row_lists else price_list
        floor = min_rate(line.get("item_code"), float(line.get("conversion_factor") or 1), line_list, warehouse, branch)
        rate = float(line.get("rate") or 0)
        # sf_trading checks ERPNext's net rate: after the document's
        # additional discount, tax left out.
        net = float(line["net_rate"]) if line.get("net_rate") is not None else rate
        if floor and net + 0.0001 < floor:
            name = line.get("item_name") or line.get("item_code")
            if net + 0.0001 < rate:
                out["problems"].append(
                    frappe._("{0}: rate {1} comes to {2} net of the invoice discount and tax, below the minimum {3}.").format(
                        name, rate, round(net, 2), round(floor, 2)
                    )
                )
            else:
                out["problems"].append(
                    frappe._("{0}: rate {1} is below the minimum {2}.").format(name, rate, round(floor, 2))
                )
    return out


def _order_limit_refusal(customer: str, company: str, mode: Optional[str]) -> Optional[str]:
    """sf_trading's Sales Order cash limits (customer's and salesman's
    payment days, cash limit, branch cash limit), asked ahead without saving:
    its own validator on the order as the app would make it. The text it
    refuses with, or None."""
    try:
        from sf_trading.sales_order_limits import validate_sales_order_limits
    except ImportError:
        return None
    from vansale.api.me import current_user_sales_person, van_default

    order = frappe._dict(
        doctype="Sales Order",
        company=company,
        customer=customer,
        custom_sales_person=current_user_sales_person(),
        branch=van_default("Branch"),
        custom_payment_mode=mode,
        transaction_date=frappe.utils.nowdate(),
    )
    messages = list(frappe.local.message_log)
    try:
        validate_sales_order_limits(order)
    except frappe.ValidationError as refusal:
        return _plain(refusal) or None
    except Exception:
        frappe.log_error(title="vansale: order limit pre-check")
    finally:
        # The refusal also queued a popup; this was only a question.
        frappe.local.message_log = messages
    return None


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


def loyalty_config(company: Optional[str]) -> Optional[dict]:
    """Steel Force "Loyalty": a small amount written off when the customer
    pays (sf_trading's write-off on its payment function), up to the
    company's Max Payment Write Off. {"max": ...}, or None where it is not
    set up (other sites, no Write Off Account / no maximum)."""
    if not is_active() or not company:
        return None
    try:
        from sf_trading.api import sales_invoice_payment  # noqa: F401
    except ImportError:
        return None
    meta = frappe.get_meta("Company")
    if not meta.has_field("custom_max_payment_write_off"):
        return None
    row = frappe.db.get_value("Company", company, ["write_off_account", "custom_max_payment_write_off"], as_dict=True)
    if not row or not row.write_off_account or float(row.custom_max_payment_write_off or 0) <= 0:
        return None
    return {"max": float(row.custom_max_payment_write_off)}


def loyalty_problem(customer: str, company: str, amount: float, orders=()) -> Optional[str]:
    """Why sf_trading would refuse this loyalty, asked before anything is
    saved (its own checks: the company maximum, loyalty already given on the
    orders this sale bills, an unapplied order advance that carried loyalty).
    None = fine."""
    from frappe import _

    amount = float(amount or 0)
    if amount <= 0:
        return None
    config = loyalty_config(company)
    if not config:
        return _("Loyalty is not set up for {0}").format(company)
    if amount - config["max"] > 0.0001:
        return _("Loyalty {0} is more than the company limit of {1}").format(amount, config["max"])
    from sf_trading.api.sales_invoice_payment import loyalty_already_given, unapplied_order_advance

    orders = [o for o in orders or [] if o]
    if orders:
        already = loyalty_already_given(frappe._dict(items=[frappe._dict(sales_order=o) for o in orders]))
        if already["amount"] > 0.0001:
            return _("Loyalty of {0} was already given on {1}").format(already["amount"], ", ".join(already["orders"]))
    unapplied = unapplied_order_advance(customer, company)
    if unapplied["loyalty"] > 0.0001:
        return _("{0} holds an unapplied advance from {1} that already carried loyalty").format(
            customer, ", ".join(unapplied["orders"])
        )
    return None


def collect_invoice(inv, rows: list[dict], entry_status: str, write_off: float = 0):
    """Payment Entries for a submitted sale the way the Steel Force desk makes
    them: sf_trading's `create_pos_payments_for_invoice` (one entry per mode,
    PDC fields for a cheque, its write-off = loyalty, branch rules), the cheque
    first and the other modes after, the loyalty on the last call — as the
    desk's cheque dialog does.

    Returns (entries made, rows left for the standard path), or None to leave
    everything to the standard path (other sites). A cheque always goes
    through sf_trading (it decides whether the cheque waits in Draft); the
    other modes only when entries are submitted at once (sf_trading always
    submits), else they are left for the standard draft path."""
    if not rows or not is_active():
        return None
    try:
        from sf_trading.api.sales_invoice_payment import create_pos_payments_for_invoice
    except ImportError:
        return None
    cheque = [r for r in rows if r.get("reference_date")]
    others = [r for r in rows if not r.get("reference_date")]
    if entry_status != "Submit" and not cheque:
        return None
    write_off = float(write_off or 0)
    due = float(inv.outstanding_amount or 0) - write_off

    def take(group: list[dict]) -> list[dict]:
        nonlocal due
        out = []
        for row in group:
            amount = min(float(row["amount"]) if row.get("amount") is not None else due, due)
            if amount <= 0:
                continue
            out.append({"mode_of_payment": row["mode_of_payment"], "amount": amount})
            due -= amount
        return out

    cheque_payments = take(cheque)
    other_payments = take(others) if entry_status == "Submit" else []
    left = [] if entry_status == "Submit" else others
    names: list[str] = []
    if cheque_payments:
        names += create_pos_payments_for_invoice(
            inv.name,
            cheque_payments,
            cheque_date=cheque[0]["reference_date"],
            cheque_no=cheque[0].get("reference_no"),
            posting_date=str(inv.posting_date),
            write_off_amount=0 if other_payments else write_off,
        ) or []
    if other_payments:
        names += create_pos_payments_for_invoice(
            inv.name, other_payments, posting_date=str(inv.posting_date), write_off_amount=write_off
        ) or []
    return names, left


def collect_customer(
    invoices: list[dict],
    amount: float,
    mode: str,
    reference_no: Optional[str],
    reference_date,
    write_off: float = 0,
    posting_date=None,
) -> Optional[list[str]]:
    """A collection from the customer screen, the Steel Force desk way: the
    amount paid oldest-first over `invoices` (already this company's, their
    outstanding less drafts), one sf_trading `create_pos_payments_for_invoice`
    call per invoice — a cheque mode as a post-dated cheque (number and date;
    sf_trading may keep it in Draft), the loyalty on the last invoice paid.

    Returns the entries made, or None on other sites (standard path). Money
    beyond the invoices is refused: sf_trading refuses a receipt that names
    no invoice (its voucher gate) and never overpays one."""
    if not is_active():
        return None
    try:
        from sf_trading.api.sales_invoice_payment import create_pos_payments_for_invoice
    except ImportError:
        return None
    from frappe import _
    from frappe.utils import flt

    is_cheque = mode in cheque_modes()
    if is_cheque and not ((reference_no or "").strip() and reference_date):
        frappe.throw(_("Enter the cheque number and date"))
    plan = []
    left = flt(amount)
    for inv in invoices:
        if left <= 0.005:
            break
        due = flt(inv.get("outstanding_amount"))
        if due <= 0.005:
            continue
        pay = min(left, due)
        plan.append([inv["name"], pay, due])
        left -= pay
    if not plan:
        frappe.throw(_("Nothing is open to collect: pick an invoice, or the customer owes nothing"))
    if left > 0.005:
        from frappe.utils import fmt_money

        frappe.throw(
            _("{0} is more than the open invoices ({1}); collect up to that amount").format(
                fmt_money(flt(amount)), fmt_money(flt(amount) - left)
            )
        )
    write_off = flt(write_off)
    if write_off:
        last = plan[-1]
        if last[1] + write_off - last[2] > 0.0001:
            from frappe.utils import fmt_money

            frappe.throw(
                _("Loyalty {0} is more than what is left on {1} after this payment ({2})").format(
                    write_off, last[0], fmt_money(flt(last[2] - last[1]))
                )
            )
    names: list[str] = []
    for idx, (invoice, pay, _due) in enumerate(plan):
        names += create_pos_payments_for_invoice(
            invoice,
            [{"mode_of_payment": mode, "amount": pay}],
            cheque_date=str(reference_date) if is_cheque else None,
            cheque_no=reference_no.strip() if is_cheque else None,
            posting_date=str(posting_date) if posting_date else None,
            write_off_amount=write_off if idx == len(plan) - 1 else 0,
        ) or []
    return names


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
