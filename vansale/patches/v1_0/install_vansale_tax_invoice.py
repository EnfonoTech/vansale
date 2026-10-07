"""Upsert the app's print formats from their HTML files.

Sources the Jinja HTML from the app's print_format folder so the file is
the single source of truth — re-running (e.g. after edits) keeps the DB row
in sync with the file. Safe to run repeatedly. Also called from
`setup.after_migrate`, since `install-app` marks patches done without
running them.
"""

from __future__ import annotations

import os

import frappe

FORMAT_NAME = "Vansale Tax Invoice"
DOC_TYPE = "Sales Invoice"

# (print format name, doctype) — HTML lives in print_format/<scrubbed name>/<scrubbed name>.html
PRINT_FORMATS = (
    (FORMAT_NAME, DOC_TYPE),
    ("Vansale Payment Receipt", "Payment Entry"),
)


def _load_html(format_name: str) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    folder = frappe.scrub(format_name)
    # vansale/patches/v1_0/ → vansale/vansale/print_format/<folder>/<folder>.html
    html_path = os.path.normpath(
        os.path.join(here, "..", "..", "vansale", "print_format", folder, f"{folder}.html")
    )
    with open(html_path, "r", encoding="utf-8") as fh:
        return fh.read()


def upsert(format_name: str, doc_type: str) -> None:
    html = _load_html(format_name)
    if frappe.db.exists("Print Format", format_name):
        doc = frappe.get_doc("Print Format", format_name)
        changed = False
        if doc.html != html:
            doc.html = html
            changed = True
        if doc.doc_type != doc_type:
            doc.doc_type = doc_type
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
    doc.name = format_name
    doc.doc_type = doc_type
    doc.module = "Vansale"
    doc.print_format_type = "Jinja"
    doc.standard = "Yes"
    doc.custom_format = 0
    doc.html = html
    doc.insert(ignore_permissions=True)


def execute() -> None:
    for format_name, doc_type in PRINT_FORMATS:
        upsert(format_name, doc_type)
