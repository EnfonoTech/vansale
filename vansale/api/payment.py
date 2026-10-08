"""Payment Entry endpoints.

`save` is idempotent by `client_id` exactly like invoices. Supports cash
and bank modes; extends via `mode_of_payment` which maps to a Mode of
Payment doc.
"""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _
from frappe.utils import cint, flt

from vansale.api.access import check_read, readable_doc
from vansale.api.me import is_office_user
from vansale.api.outbox import claim
from vansale.api.datetime_util import naive_site_to_utc_iso, parse_client_ts


def _record_outbox(client_id: str, ref_name: str, posting_ts: Optional[str], payload: dict) -> None:
    if not client_id:
        return
    if frappe.db.exists("Vansale Outbox", client_id):
        doc = frappe.get_doc("Vansale Outbox", client_id)
    else:
        doc = frappe.new_doc("Vansale Outbox")
        doc.client_id = client_id
    doc.event_type = "payment"
    doc.user = frappe.session.user
    doc.client_ts = parse_client_ts(posting_ts) if posting_ts else None
    doc.drained_at = frappe.utils.now_datetime()
    doc.status = "processed"
    doc.ref_doctype = "Payment Entry"
    doc.ref_name = ref_name
    doc.payload_json = frappe.as_json(payload)
    doc.save(ignore_permissions=True)


def _resolve_accounts(company: str, mode_of_payment: str) -> tuple[str, str]:
    """Return (paid_from, paid_to). paid_from is customer's receivable; paid_to is the bank/cash."""
    receivable = frappe.db.get_value(
        "Company", company, "default_receivable_account"
    ) or frappe.db.get_value(
        "Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "name"
    )
    paid_to = frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": mode_of_payment, "company": company},
        "default_account",
    )
    if not paid_to:
        # Used to fall back to the company's first Cash/Bank account, which
        # booked e.g. a card payment into the cash account without telling
        # anyone. The office must set the account on the Mode of Payment.
        frappe.throw(
            _("Mode of Payment {0} has no account for company {1}. Ask the office to set it.").format(
                mode_of_payment, company
            )
        )
    if not receivable:
        frappe.throw(_("Could not resolve accounts for payment — set defaults on Company."))
    return receivable, paid_to


def build_payment_entry(
    company: str,
    customer: str,
    amount: float,
    mode_of_payment: str,
    posting_date,
    reference_no: Optional[str] = None,
    reference_date=None,
    remarks: Optional[str] = None,
):
    """Unsaved "Receive" Payment Entry from a customer (no references yet).

    Shared by the payment screen (`save`) and cash sales posted as a
    Payment Entry (`invoice.save`).
    """
    paid_from, paid_to = _resolve_accounts(company, mode_of_payment)
    # Account currencies — required by ERPNext's Payment Entry validation;
    # skipping this made validate() trip on str vs Dict attribute access.
    paid_from_currency = frappe.db.get_value("Account", paid_from, "account_currency") or "SAR"
    paid_to_currency = frappe.db.get_value("Account", paid_to, "account_currency") or "SAR"

    doc = frappe.new_doc("Payment Entry")
    doc.payment_type = "Receive"
    doc.party_type = "Customer"
    doc.party = customer
    doc.company = company
    doc.mode_of_payment = mode_of_payment
    doc.paid_amount = amount
    doc.received_amount = amount
    doc.paid_from = paid_from
    doc.paid_to = paid_to
    doc.paid_from_account_currency = paid_from_currency
    doc.paid_to_account_currency = paid_to_currency
    # NOTE: do NOT call doc.setup_party_account_field() — it's gone in
    # ERPNext v15. For Receive, party_account == paid_from (Debtors).
    doc.party_account = paid_from
    doc.party_account_currency = paid_from_currency
    doc.source_exchange_rate = 1
    doc.target_exchange_rate = 1
    doc.reference_no = reference_no
    doc.reference_date = reference_date
    doc.posting_date = posting_date
    doc.remarks = remarks
    return doc


def pending_by_invoice(invoices: list[str]) -> dict[str, float]:
    """Amount allocated to each invoice by draft Payment Entries — collected
    in the field but not yet submitted by the office. ERPNext's
    outstanding_amount ignores drafts, so without this the app offered the
    same money for collection again."""
    if not invoices:
        return {}
    return {
        r[0]: flt(r[1])
        for r in frappe.db.sql(
            """
            SELECT r.reference_name, SUM(r.allocated_amount)
            FROM `tabPayment Entry Reference` r
            JOIN `tabPayment Entry` p ON p.name = r.parent
            WHERE p.docstatus = 0 AND r.reference_doctype = 'Sales Invoice'
              AND r.reference_name IN %(names)s
            GROUP BY r.reference_name
            """,
            {"names": tuple(invoices)},
        )
    }


def pending_by_customer(customers: list[str]) -> dict[str, float]:
    """Total of each customer's draft (not yet submitted) receipts. Draft
    refunds ("Pay") are not collections, so they are left out."""
    if not customers:
        return {}
    return {
        r[0]: flt(r[1])
        for r in frappe.db.sql(
            """SELECT party, SUM(paid_amount) FROM `tabPayment Entry`
               WHERE docstatus = 0 AND party_type = 'Customer' AND payment_type = 'Receive'
                 AND party IN %(names)s
               GROUP BY party""",
            {"names": tuple(customers)},
        )
    }


def pending_for_customer(customer: str) -> float:
    """Total of the customer's draft (not yet submitted) receipts."""
    return pending_by_customer([customer]).get(customer, 0.0)


def van_allowed_modes() -> Optional[set[str]]:
    """Modes of payment the user's van may use; None = no restriction."""
    from vansale.api.me import user_to_van_config

    van = user_to_van_config(frappe.session.user)
    if not van:
        return None
    modes = set(
        frappe.get_all(
            "Vansale Allowed Mode of Payment",
            filters={"parent": van, "parenttype": "Vansale Configuration"},
            pluck="mode_of_payment",
        )
    )
    return modes or None


def check_mode_allowed(mode_of_payment: str) -> None:
    allowed = van_allowed_modes()
    if allowed is not None and mode_of_payment not in allowed:
        frappe.throw(_("Mode of Payment {0} is not allowed for your van").format(mode_of_payment))


def _needs_reference(company: str, mode_of_payment: str) -> bool:
    """ERPNext requires Reference No + Date when the mode's account is a Bank
    account — decided by the account, not the Mode of Payment's own type."""
    account = frappe.db.get_value(
        "Mode of Payment Account", {"parent": mode_of_payment, "company": company}, "default_account"
    )
    return bool(account) and frappe.db.get_value("Account", account, "account_type") == "Bank"


def submit_if_configured(pe, status: str | None = None, setting: str = "Cash sale / refund status") -> None:
    """Submit per the Payment Entry status setting (else leave a draft for
    the office), with a clear message when the user may not submit.

    `status` defaults to the cash-sale / refund status; Payment Collection
    passes its own, and `setting` names it in the message."""
    from vansale.api.me import cash_sale_settings

    if (status or cash_sale_settings()["payment_entry_status"]) != "Submit":
        return
    if not frappe.has_permission("Payment Entry", "submit", doc=pe):
        frappe.throw(
            _("No permission to submit Payment Entry. Set \"{0}\" to Draft.").format(_(setting)),
            frappe.PermissionError,
        )
    pe.submit()


def allocate(doc, invoices: list[dict], amount: float) -> None:
    """Allocate `amount` FIFO over `invoices` (name, grand_total, outstanding_amount)."""
    remaining = amount
    for inv in invoices:
        if remaining <= 0:
            break
        out = float(inv["outstanding_amount"] or 0)
        if out <= 0:
            continue
        alloc = min(remaining, out)
        doc.append(
            "references",
            {
                "reference_doctype": "Sales Invoice",
                "reference_name": inv["name"],
                "total_amount": float(inv["grand_total"] or 0),
                "outstanding_amount": out,
                "allocated_amount": alloc,
            },
        )
        remaining -= alloc


@frappe.whitelist(methods=["POST"])
def save(
    client_id: str,
    customer: str,
    paid_amount: float,
    mode_of_payment: str = "Cash",
    reference_no: Optional[str] = None,
    reference_date: Optional[str] = None,
    invoice_name: Optional[str] = None,
    invoice_names: Optional[list[str]] = None,
    posting_ts: Optional[str] = None,
    remarks: Optional[str] = None,
    submit: int = 1,
    advance: int = 0,
) -> dict:
    """
    Allocation rules (PDF §2d):
      - `advance` (setting "Allow advance payment") → no allocation at all;
                                          the whole amount stays as the
                                          customer's advance / credit
      - `invoice_names` list provided   → allocate FIFO across the picked
                                          invoices in the given order
      - `invoice_name` single provided  → allocate against that invoice only
      - neither provided                → FIFO auto-allocate across ALL
                                          outstanding invoices for the
                                          customer, oldest first; any
                                          leftover remains unallocated
                                          (customer credit)
    """
    if not client_id:
        frappe.throw(_("client_id is required"))
    if not customer:
        frappe.throw(_("Customer required"))
    try:
        amount = float(paid_amount)
    except (TypeError, ValueError):
        frappe.throw(_("Invalid amount"))
    if amount <= 0:
        frappe.throw(_("Amount must be positive"))
    advance = cint(advance)
    if advance:
        from vansale.api.me import advance_payment_allowed

        if not advance_payment_allowed():
            frappe.throw(_("Advance payments are not enabled for your van"), frappe.PermissionError)

    existing = claim(client_id, "payment", "Payment Entry")
    if existing:
        doc = frappe.get_doc("Payment Entry", existing)
        return {
            "name": doc.name,
            "paid_amount": float(doc.paid_amount or 0),
            "status": doc.status,
            "modified": naive_site_to_utc_iso(doc.modified),
            "idempotent_replay": True,
        }

    company = (
        frappe.db.get_value(
            "User Permission",
            {"user": frappe.session.user, "allow": "Company", "is_default": 1},
            "for_value",
        )
        or frappe.defaults.get_user_default("Company", frappe.session.user)
        or frappe.db.get_single_value("Global Defaults", "default_company")
    )
    posting = parse_client_ts(posting_ts) if posting_ts else frappe.utils.now_datetime()
    # ERPNext requires Reference No + Date on bank-type modes. The date was
    # never sent, so every bank collection failed; default it to the posting
    # date and ask for the number up front.
    check_mode_allowed(mode_of_payment)
    if not reference_no and _needs_reference(company, mode_of_payment):
        frappe.throw(_("Enter the reference number (transaction / cheque no.) for {0}").format(mode_of_payment))
    doc = build_payment_entry(
        company, customer, amount, mode_of_payment, posting.date(),
        reference_no=reference_no,
        reference_date=reference_date or (posting.date() if reference_no else None),
        remarks=remarks,
    )

    # Build the list of invoices to allocate against (FIFO order).
    target_invoices: list[dict] = []
    if advance:
        pass  # advance: nothing allocated
    elif invoice_names:
        # Explicit multi-pick — respect caller order.
        for n in invoice_names:
            inv = frappe.db.get_value(
                "Sales Invoice",
                n,
                ["name", "grand_total", "outstanding_amount"],
                as_dict=True,
            )
            if inv and float(inv.outstanding_amount or 0) > 0:
                target_invoices.append(inv)
    elif invoice_name:
        inv = frappe.db.get_value(
            "Sales Invoice",
            invoice_name,
            ["name", "grand_total", "outstanding_amount"],
            as_dict=True,
        )
        if inv:
            target_invoices.append(inv)
    else:
        # Auto-FIFO: oldest outstanding invoices first, until amount exhausted.
        target_invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": customer,
                "docstatus": 1,
                "outstanding_amount": [">", 0],
            },
            fields=["name", "grand_total", "outstanding_amount"],
            order_by="posting_date asc, creation asc",
        )

    # Allocate only what isn't already covered by draft Payment Entries.
    pending = pending_by_invoice([inv["name"] for inv in target_invoices])
    for inv in target_invoices:
        inv["outstanding_amount"] = max(flt(inv["outstanding_amount"]) - pending.get(inv["name"], 0.0), 0.0)
    allocate(doc, target_invoices, amount)
    doc.insert(ignore_permissions=False)
    # Collections have their own Draft / Submit setting (default: same as
    # the cash sale): some sites post at once, others leave drafts for the office.
    if submit:
        from vansale.api.me import collection_payment_entry_status

        submit_if_configured(
            doc, collection_payment_entry_status(), setting="Payment collection status"
        )

    _record_outbox(client_id, doc.name, posting_ts, {
        "customer": customer,
        "amount": amount,
        "mode_of_payment": mode_of_payment,
        "invoice_name": invoice_name,
        "advance": advance,
    })
    frappe.db.commit()

    return {
        "name": doc.name,
        "paid_amount": float(doc.paid_amount or 0),
        "status": doc.status,
        "modified": naive_site_to_utc_iso(doc.modified),
        "idempotent_replay": False,
    }


@frappe.whitelist(methods=["GET"])
def list_mine(limit: int = 50, customer: Optional[str] = None) -> list[dict]:
    """Payment Entries visible to this user.

    Van users see Payment Entries they created (owner = session.user) —
    both drafts and submitted. Admins (System Manager / Van Manager /
    Accounts Manager) see everything. Drafts are included so the UI can
    offer Edit/Delete actions on unsubmitted entries; the Payment
    Detail view already gates submit/delete buttons on docstatus.
    """
    is_admin = is_office_user(default_roles={"System Manager", "Van Manager", "Accounts Manager"})

    filters: dict = {"docstatus": ["<", 2]}  # drafts + submitted (not cancelled)
    if customer:
        filters["party"] = customer
    if not is_admin:
        filters["owner"] = frappe.session.user
    rows = frappe.get_all(
        "Payment Entry",
        filters=filters,
        fields=[
            "name", "party", "party_name", "paid_amount", "mode_of_payment",
            "posting_date", "modified", "docstatus", "status", "payment_type",
        ],
        order_by="posting_date desc, modified desc",
        limit=int(limit),
    )
    for r in rows:
        r["modified"] = naive_site_to_utc_iso(r.get("modified"))
        r["posting_date"] = str(r["posting_date"]) if r.get("posting_date") else None
    return rows


@frappe.whitelist(methods=["POST"])
def delete_payment(name: str) -> dict:
    """Delete a Payment Entry — drafts only.

    Submitted Payment Entries require a cancel + separate accounting
    entry to reverse GL impact; we intentionally refuse to cancel from
    the PWA to prevent accidental GL reversal. The user must open the
    Desk and go through the Cancel workflow there if they really need to.
    """
    if not name:
        frappe.throw(_("Payment name required"))
    doc = frappe.get_doc("Payment Entry", name)
    if doc.docstatus != 0:
        frappe.throw(_("Only draft payments can be deleted here. Submitted payments must be cancelled from the Desk."))
    # Ownership check — non-admins can only delete their own drafts.
    is_admin = is_office_user(default_roles={"System Manager", "Van Manager", "Accounts Manager"})
    if not is_admin and doc.owner != frappe.session.user:
        frappe.throw(_("You can only delete your own draft payments."))
    frappe.delete_doc("Payment Entry", name, ignore_permissions=False)
    return {"deleted": True, "name": name}


@frappe.whitelist(methods=["GET"])
def outstanding(customer: str) -> list[dict]:
    """Return submitted, unpaid Sales Invoices for a customer.

    ``ignore_permissions=True`` because the Van User role may not have a
    User Permission for every customer's invoices — but when collecting
    payment for a customer they are assigned to, they must see all
    outstanding regardless of which rep originally billed them.

    ``posting_date`` / ``due_date`` are ``datetime.date`` (not datetime),
    so we stringify them — ``naive_site_to_utc_iso`` expects a datetime
    and crashes on a plain date with ``AttributeError: tzinfo``.
    """
    # All of the customer's open invoices (any salesman's), but only for a
    # customer this user may read.
    check_read("Customer", customer)
    rows = frappe.get_all(
        "Sales Invoice",
        filters={"customer": customer, "docstatus": 1, "outstanding_amount": [">", 0]},
        fields=["name", "grand_total", "outstanding_amount", "posting_date", "status", "due_date"],
        order_by="posting_date asc",
        ignore_permissions=True,
    )
    pending = pending_by_invoice([r["name"] for r in rows])
    for r in rows:
        r["posting_date"] = str(r["posting_date"]) if r.get("posting_date") else None
        r["due_date"] = str(r["due_date"]) if r.get("due_date") else None
        # Collected but waiting for the office to submit the Payment Entry.
        r["pending_amount"] = pending.get(r["name"], 0.0)
        r["outstanding_amount"] = max(flt(r["outstanding_amount"]) - r["pending_amount"], 0.0)
    return [r for r in rows if r["outstanding_amount"] > 0 or r["pending_amount"] > 0]


@frappe.whitelist(methods=["GET"])
def detail(name: str) -> dict:
    """Return a Payment Entry with expanded references (invoices covered).

    Used by the in-app Payment Detail view — the one the PWA opens after
    a successful save so the user can eyeball exactly what was written
    (amount, mode, posting date, invoices covered, remarks) without
    bouncing back to the dashboard.

    `posting_date` is a `datetime.date` (not datetime); stringify it
    directly rather than routing through `naive_site_to_utc_iso`
    (which expects a datetime and crashes on a plain date — see the
    `outstanding()` comment above).
    """
    if not name:
        frappe.throw(_("name required"))
    doc = readable_doc("Payment Entry", name)
    refs = [
        {
            "reference_doctype": r.reference_doctype,
            "reference_name": r.reference_name,
            "allocated_amount": float(r.allocated_amount or 0),
            "total_amount": float(r.total_amount or 0),
            "outstanding_amount": float(r.outstanding_amount or 0),
        }
        for r in (doc.references or [])
    ]
    return {
        "name": doc.name,
        "party": doc.party,
        "party_name": doc.party_name,
        "payment_type": doc.payment_type,
        "paid_amount": float(doc.paid_amount or 0),
        "received_amount": float(doc.received_amount or 0),
        "mode_of_payment": doc.mode_of_payment,
        "reference_no": doc.reference_no,
        "reference_date": str(doc.reference_date) if doc.reference_date else None,
        "posting_date": str(doc.posting_date) if doc.posting_date else None,
        "remarks": doc.remarks,
        "status": doc.status,
        "docstatus": int(doc.docstatus or 0),
        "references": refs,
        "modified": naive_site_to_utc_iso(doc.modified),
    }


@frappe.whitelist(methods=["GET"])
def modes_of_payment() -> list[dict]:
    """Enabled Modes of Payment that have an account for the user's company.

    A mode without an account cannot be posted, so offering it only produced
    a failed sale (or, offline, a stuck sync entry).
    """
    from vansale.api.invoice import _user_company

    company = _user_company()
    with_account = frappe.get_all(
        "Mode of Payment Account",
        filters={"company": company, "default_account": ["is", "set"]},
        pluck="parent",
    )
    rows = frappe.get_all(
        "Mode of Payment",
        filters={"enabled": 1, "name": ["in", with_account or [""]]},
        fields=["name", "type"],
        order_by="name asc",
    )
    allowed = van_allowed_modes()
    if allowed is not None:
        rows = [r for r in rows if r["name"] in allowed]
    for row in rows:
        row["needs_reference"] = _needs_reference(company, row["name"])
    return rows
