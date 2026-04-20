"""Upsert the `Vansale Tax Invoice` Print Format.

Sources the Jinja HTML from the app's print_format folder so the file is
the single source of truth — re-running the patch (e.g. after edits) keeps
the DB row in sync with the file. Safe to run repeatedly.
"""

from __future__ import annotations

import os

import frappe

FORMAT_NAME = "Vansale Tax Invoice"
DOC_TYPE = "Sales Invoice"


def _load_html() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    # vansale/patches/v1_0/ → vansale/vansale/print_format/vansale_tax_invoice/…
    html_path = os.path.normpath(
        os.path.join(
            here,
            "..",
            "..",
            "vansale",
            "print_format",
            "vansale_tax_invoice",
            "vansale_tax_invoice.html",
        )
    )
    with open(html_path, "r", encoding="utf-8") as fh:
        return fh.read()


def execute() -> None:
    html = _load_html()
    if frappe.db.exists("Print Format", FORMAT_NAME):
        doc = frappe.get_doc("Print Format", FORMAT_NAME)
        changed = False
        if doc.html != html:
            doc.html = html
            changed = True
        if doc.doc_type != DOC_TYPE:
            doc.doc_type = DOC_TYPE
            changed = True
        if doc.print_format_type != "Jinja":
            doc.print_format_type = "Jinja"
            changed = True
        if doc.standard != "Yes":
            doc.standard = "Yes"
            changed = True
        if changed:
            doc.save(ignore_permissions=True)
        return

    doc = frappe.new_doc("Print Format")
    doc.name = FORMAT_NAME
    doc.doc_type = DOC_TYPE
    doc.module = "Vansale"
    doc.print_format_type = "Jinja"
    doc.standard = "Yes"
    doc.custom_format = 0
    doc.html = html
    doc.insert(ignore_permissions=True)
