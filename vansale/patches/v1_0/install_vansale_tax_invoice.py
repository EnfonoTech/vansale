"""Upsert the app's print formats from their HTML files.

Sources the Jinja HTML from the app's print_format folder so the file is
the single source of truth — re-running (e.g. after edits) keeps the DB row
in sync with the file. Safe to run repeatedly. Also called from
`setup.after_migrate`, since `install-app` marks patches done without
running them.

Developer mode on (dev sites): a *standard* format, as before. Frappe lets
`PrintFormat.validate` save a standard format only in developer mode, inside
a migrate/install, or in a test; anywhere else (`bench execute`, a console,
a hook run by hand) it raises "Standard Print Format cannot be updated".
Developer mode off (production): a *custom* format (`standard = No`,
`custom_format = 1`), which Frappe saves in any context. `custom_format` is
needed: printview renders a format's own HTML only when `custom_format` is on
or `standard` is Yes, and falls back to the generic layout otherwise. The
format keeps `module = Vansale`, so printview still reads the file from the
app folder and a deploy updates the print with no migrate.
"""

from __future__ import annotations

import os

import frappe
from frappe.utils import cint

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


def _is_developer_mode() -> bool:
    return bool(cint(frappe.conf.get("developer_mode")))


def _wanted_flags() -> dict:
    """`standard` / `custom_format` for this site (see the module docstring).
    Developer mode leaves `custom_format` alone: a standard format renders
    from its file without it."""
    if _is_developer_mode():
        return {"standard": "Yes"}
    return {"standard": "No", "custom_format": 1}


def upsert(format_name: str, doc_type: str) -> None:
    html = _load_html(format_name)
    wanted = {"doc_type": doc_type, "print_format_type": "Jinja", "html": html, **_wanted_flags()}

    if frappe.db.exists("Print Format", format_name):
        doc = frappe.get_doc("Print Format", format_name)
        changed = False
        for field, value in wanted.items():
            if doc.get(field) != value:
                doc.set(field, value)
                changed = True
        if changed:
            doc.save(ignore_permissions=True)
        return

    doc = frappe.new_doc("Print Format")
    doc.name = format_name
    doc.module = "Vansale"
    doc.custom_format = 0
    doc.update(wanted)
    doc.insert(ignore_permissions=True)


def execute() -> None:
    for format_name, doc_type in PRINT_FORMATS:
        upsert(format_name, doc_type)
