"""Printing for the app.

`get_html`: the print format as desk's /printview renders it (format HTML, Print
Style and Frappe's print.bundle.css), so the in-app preview and web print
look the same as printing from desk.

`pdf`: Android prints a PDF (the WebView ignores window.print). Copies are
the document's pages repeated in one PDF, so the driver gets them in one job.
"""

from __future__ import annotations

import io

import frappe
from frappe import _
from frappe.utils import cint

PRINTABLE = ("Sales Invoice", "Payment Entry")
MAX_COPIES = 10


def _printable(doctype: str, name: str):
    if doctype not in PRINTABLE:
        frappe.throw(_("Cannot print {0} from the app").format(doctype))
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("print")
    return doc


@frappe.whitelist(methods=["GET"])
def get_html(doctype: str, name: str, format: str | None = None, no_letterhead: int = 0) -> dict:
    """Body + styles of the print format, with what /printview adds around them.

    Not named `html`: Frappe's nginx config rewrites any path ending in
    ".html" (`/api/method/vansale.api.printing.html` → `…printing`), so
    behind nginx the call hit the module and failed with 417."""
    from frappe.utils.jinja_globals import bundled_asset, is_rtl
    from frappe.www.printview import get_html_and_style

    _printable(doctype, name)
    out = get_html_and_style(doctype, name, print_format=format, no_letterhead=cint(no_letterhead))
    return {
        "html": out.get("html"),
        "style": out.get("style"),
        # Frappe's print CSS (tables, grid, fonts) — desk's printview links it.
        "print_css": bundled_asset("print.bundle.css"),
        "dir": "rtl" if is_rtl() else "ltr",
        "lang": frappe.local.lang,
    }


@frappe.whitelist(methods=["GET"])
def pdf(doctype: str, name: str, format: str | None = None, copies: int = 1, no_letterhead: int = 0):
    doc = _printable(doctype, name)

    data = frappe.get_print(
        doctype, name, format, doc=doc, as_pdf=True, no_letterhead=cint(no_letterhead)
    )
    copies = max(1, min(cint(copies), MAX_COPIES))
    if copies > 1:
        from pypdf import PdfReader, PdfWriter

        pages = PdfReader(io.BytesIO(data)).pages
        writer = PdfWriter()
        for _copy in range(copies):
            for page in pages:
                writer.add_page(page)
        buffer = io.BytesIO()
        writer.write(buffer)
        data = buffer.getvalue()

    frappe.local.response.filename = f"{name}.pdf"
    frappe.local.response.filecontent = data
    frappe.local.response.type = "pdf"
