"""Van Visit Compliance — planned stops vs stops actually served.

`Van Daily Visit` is the plan: one row per customer per day with a status the
driver moves through. This report is the "did the route get run" view, and the
number the office actually acts on is `not_visited` — a stop left pending is
indistinguishable from a stop the driver never opened the app for.

`invoiced` counts stops that produced a Sales Invoice. A high done-count with a
low invoiced-count means drivers are closing visits without selling, which is
either a stock problem or a discipline problem — the report cannot tell you
which, but it tells you where to look.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from vansale.vansale.report.vansale_report_utils import date_range, van_scope


def execute(filters=None):
    filters = frappe._dict(filters or {})

    where = ""
    values: dict = {}
    for fragment, binds in (
        date_range(filters, "visit_date"),
        van_scope(filters),
    ):
        where += fragment
        values.update(binds)

    rows = frappe.db.sql(
        f"""
        SELECT
            doc.visit_date  AS visit_date,
            vcu.parent      AS van,
            doc.user        AS user,
            COUNT(*)        AS planned,
            SUM(CASE WHEN doc.status = 'done' THEN 1 ELSE 0 END)        AS done,
            SUM(CASE WHEN doc.status = 'skipped' THEN 1 ELSE 0 END)     AS skipped,
            SUM(CASE WHEN doc.status IN ('pending', 'in_progress') THEN 1 ELSE 0 END) AS not_visited,
            SUM(CASE WHEN doc.invoice IS NOT NULL AND doc.invoice != '' THEN 1 ELSE 0 END) AS invoiced,
            SUM(CASE WHEN doc.payment IS NOT NULL AND doc.payment != '' THEN 1 ELSE 0 END) AS collected
        FROM `tabVan Daily Visit` doc
        LEFT JOIN `tabVansale Configuration User` vcu ON vcu.user = doc.user
        WHERE 1 = 1 {where}
        GROUP BY doc.visit_date, vcu.parent, doc.user
        ORDER BY doc.visit_date DESC, vcu.parent ASC
        """,
        values,
        as_dict=True,
    )

    for r in rows:
        planned = flt(r.planned)
        r["coverage_pct"] = round((flt(r.done) / planned) * 100, 1) if planned else 0.0

    return _columns(), rows


def _columns() -> list[dict]:
    return [
        {"fieldname": "visit_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
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
        {"fieldname": "planned", "label": _("Planned"), "fieldtype": "Int", "width": 90},
        {"fieldname": "done", "label": _("Visited"), "fieldtype": "Int", "width": 90},
        {"fieldname": "skipped", "label": _("Skipped"), "fieldtype": "Int", "width": 90},
        {
            "fieldname": "not_visited",
            "label": _("Not Visited"),
            "fieldtype": "Int",
            "width": 110,
        },
        {
            "fieldname": "coverage_pct",
            "label": _("Coverage %"),
            "fieldtype": "Percent",
            "width": 110,
        },
        {"fieldname": "invoiced", "label": _("Invoiced"), "fieldtype": "Int", "width": 90},
        {"fieldname": "collected", "label": _("Paid"), "fieldtype": "Int", "width": 90},
    ]
