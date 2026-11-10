# apps/vansale/vansale/sf_trading/report/pdc_report/pdc_report.py
"""PDC Report — Post-Dated / cheque payments.

Lists Payment Entries whose linked Mode of Payment carries ZATCA payment-means
code '20' (cheque). Robust against nulls / cancelled / messy reference data.

Reminder anchor: the **posting date**. The notification "PDC Cheque Date Reminder"
(Notification fixture in permission_manager) fires `REMINDER_LEAD_DAYS` days before
`Payment Entry.posting_date`, so the report's Reminder Date column is posting_date − 3.
Keep the two in step — the column exists so an accountant can see, in the report, the
day the alert lands.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

# days before the posting date that the PDC reminder notification fires
REMINDER_LEAD_DAYS = 3


def execute(filters=None):
    filters = frappe._dict(filters or {})
    return get_columns(), get_data(filters)


def get_cheque_modes():
    """Modes of Payment whose ZATCA payment means code == '20' (cheque)."""
    modes = frappe.get_all(
        "Mode of Payment",
        fields=["name", "custom_zatca_payment_means_code"],
    )
    return [m.name for m in modes if (m.custom_zatca_payment_means_code or "").strip() == "20"]


def get_data(filters):
    cheque_modes = get_cheque_modes()
    if not cheque_modes:
        return []

    conds = [
        ["Payment Entry", "mode_of_payment", "in", cheque_modes],
    ]
    if cint(filters.get("include_cancelled")):
        conds.append(["Payment Entry", "docstatus", "in", [0, 1, 2]])
    else:
        conds.append(["Payment Entry", "docstatus", "<", 2])

    for key in ("company", "payment_type", "party_type", "party", "mode_of_payment"):
        if filters.get(key):
            conds.append(["Payment Entry", key, "=", filters.get(key)])

    if filters.get("from_date"):
        conds.append(["Payment Entry", "reference_date", ">=", getdate(filters.from_date)])
    if filters.get("to_date"):
        conds.append(["Payment Entry", "reference_date", "<=", getdate(filters.to_date)])

    status = filters.get("status")
    if status == "Pending":
        conds.append(["Payment Entry", "clearance_date", "is", "not set"])
    elif status == "Cleared":
        conds.append(["Payment Entry", "clearance_date", "is", "set"])

    rows = frappe.get_all(
        "Payment Entry",
        filters=conds,
        fields=[
            "name", "payment_type", "posting_date", "reference_date", "reference_no",
            "party_type", "party", "party_name", "mode_of_payment", "paid_amount",
            "received_amount", "paid_from", "paid_to", "clearance_date", "docstatus",
            "company", "paid_from_account_currency", "paid_to_account_currency",
        ],
        order_by="reference_date asc, name asc",
    )

    today = getdate(nowdate())
    out = []
    for r in rows:
        is_receive = r.payment_type == "Receive"
        amount = flt(r.received_amount) if is_receive else flt(r.paid_amount)
        currency = r.paid_to_account_currency if is_receive else r.paid_from_account_currency
        bank = r.paid_to if is_receive else r.paid_from
        cheque_date = getdate(r.reference_date) if r.reference_date else None
        posting_date = getdate(r.posting_date) if r.posting_date else None
        days = date_diff(cheque_date, today) if cheque_date else None
        # the notification anchors on the posting date, so the report must too
        reminder_date = add_days(posting_date, -REMINDER_LEAD_DAYS) if posting_date else None
        days_to_posting = date_diff(posting_date, today) if posting_date else None
        if r.docstatus == 2:
            state = "Cancelled"
        elif r.clearance_date:
            state = "Cleared"
        else:
            state = "Pending"
        out.append({
            "payment_entry": r.name,
            "payment_type": r.payment_type,
            "posting_date": posting_date,
            "cheque_date": cheque_date,
            "reminder_date": reminder_date,
            "reference_no": r.reference_no,
            "days_to_cheque_date": days,
            "days_to_posting_date": days_to_posting,
            "status": state,
            "party_type": r.party_type,
            "party": r.party,
            "party_name": r.party_name,
            "mode_of_payment": r.mode_of_payment,
            "amount": amount,
            "currency": currency,
            "bank_account": bank,
            "clearance_date": r.clearance_date,
            "company": r.company,
        })
    return out


def get_columns():
    return [
        {"label": _("Payment Entry"), "fieldname": "payment_entry", "fieldtype": "Link", "options": "Payment Entry", "width": 165},
        {"label": _("Type"), "fieldname": "payment_type", "fieldtype": "Data", "width": 80},
        {"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 105},
        {"label": _("Reminder Date (Posting − 3)"), "fieldname": "reminder_date", "fieldtype": "Date", "width": 150},
        {"label": _("Days to Posting"), "fieldname": "days_to_posting_date", "fieldtype": "Int", "width": 105},
        {"label": _("Cheque Date"), "fieldname": "cheque_date", "fieldtype": "Date", "width": 100},
        {"label": _("Cheque / Ref No"), "fieldname": "reference_no", "fieldtype": "Data", "width": 170},
        {"label": _("Days to Cheque Date"), "fieldname": "days_to_cheque_date", "fieldtype": "Int", "width": 125},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
        {"label": _("Party Type"), "fieldname": "party_type", "fieldtype": "Data", "width": 90},
        {"label": _("Party"), "fieldname": "party", "fieldtype": "Dynamic Link", "options": "party_type", "width": 150},
        {"label": _("Party Name"), "fieldname": "party_name", "fieldtype": "Data", "width": 180},
        {"label": _("Mode of Payment"), "fieldname": "mode_of_payment", "fieldtype": "Link", "options": "Mode of Payment", "width": 120},
        {"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "options": "currency", "width": 120},
        {"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "width": 70},
        {"label": _("Bank / Cash Account"), "fieldname": "bank_account", "fieldtype": "Link", "options": "Account", "width": 170},
        {"label": _("Cleared On"), "fieldname": "clearance_date", "fieldtype": "Date", "width": 100},
        {"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 150},
    ]
