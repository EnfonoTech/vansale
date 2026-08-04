"""Van Collection Summary — receipts by van and payment mode.

Answers "how much cash is each driver carrying, and how much went to the bank
or a card machine". Only `Receive` entries count; a refund to a customer is a
`Pay` and must not be netted into a driver's cash bag silently.

Unallocated receipts (money taken without being applied to an invoice) are
called out separately, because they are the usual cause of a customer
statement disagreeing with what the driver says they collected.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from vansale.vansale.report.vansale_report_utils import (
    company_scope,
    date_range,
    van_scope,
)


def execute(filters=None):
    filters = frappe._dict(filters or {})

    where = ""
    values: dict = {}
    for fragment, binds in (
        date_range(filters, "posting_date"),
        van_scope(filters),
        company_scope(filters),
    ):
        where += fragment
        values.update(binds)

    if filters.get("mode_of_payment"):
        where += " AND doc.mode_of_payment = %(mode_of_payment)s"
        values["mode_of_payment"] = filters["mode_of_payment"]

    rows = frappe.db.sql(
        f"""
        SELECT
            doc.posting_date                    AS posting_date,
            vcu.parent                          AS van,
            doc.owner                           AS user,
            doc.mode_of_payment                 AS mode_of_payment,
            COUNT(DISTINCT doc.name)            AS receipts,
            SUM(doc.base_paid_amount)           AS collected,
            SUM(doc.unallocated_amount)         AS unallocated
        FROM `tabPayment Entry` doc
        LEFT JOIN `tabVansale Configuration User` vcu ON vcu.user = doc.owner
        WHERE doc.docstatus = 1
          AND doc.payment_type = 'Receive'
          AND doc.party_type = 'Customer'
          {where}
        GROUP BY doc.posting_date, vcu.parent, doc.owner, doc.mode_of_payment
        ORDER BY doc.posting_date DESC, vcu.parent ASC, doc.mode_of_payment ASC
        """,
        values,
        as_dict=True,
    )

    for r in rows:
        r["allocated"] = flt(r.collected) - flt(r.unallocated)

    return _columns(), rows


def _columns() -> list[dict]:
    return [
        {"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
        {
            "fieldname": "van",
            "label": _("Van"),
            "fieldtype": "Link",
            "options": "Vansale Configuration",
            "width": 150,
        },
        {
            "fieldname": "user",
            "label": _("Driver"),
            "fieldtype": "Link",
            "options": "User",
            "width": 180,
        },
        {
            "fieldname": "mode_of_payment",
            "label": _("Mode of Payment"),
            "fieldtype": "Link",
            "options": "Mode of Payment",
            "width": 150,
        },
        {"fieldname": "receipts", "label": _("Receipts"), "fieldtype": "Int", "width": 90},
        {
            "fieldname": "collected",
            "label": _("Collected"),
            "fieldtype": "Currency",
            "width": 130,
        },
        {
            "fieldname": "allocated",
            "label": _("Applied to Invoices"),
            "fieldtype": "Currency",
            "width": 160,
        },
        {
            "fieldname": "unallocated",
            "label": _("Unapplied"),
            "fieldtype": "Currency",
            "width": 130,
        },
    ]
