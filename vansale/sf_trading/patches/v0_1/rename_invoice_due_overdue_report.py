# apps/vansale/vansale/sf_trading/patches/v0_1/rename_invoice_due_overdue_report.py
"""Rename "Invoice Due & Overdue Report" -> "Invoice Due and Overdue Report".

Frappe derives a Script Report's python module from its NAME, so an ampersand produced
`vansale.sf_trading.report.invoice_due_&_overdue_report`, which is not an importable module.
Opening the report in the desk failed with ModuleNotFoundError; only direct execute() calls
worked, which is how it slipped through.
"""

import frappe

OLD = "Invoice Due & Overdue Report"
NEW = "Invoice Due and Overdue Report"


def execute():
    if not frappe.db.exists("Report", OLD):
        return

    if frappe.db.exists("Report", NEW):
        # the app file already created the correct one; drop the broken record
        frappe.delete_doc("Report", OLD, force=True, ignore_permissions=True)
        return

    frappe.rename_doc("Report", OLD, NEW, force=True, ignore_permissions=True)
    frappe.db.commit()
