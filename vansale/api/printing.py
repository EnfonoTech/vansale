"""PDF for the app's print button, with copies.

Android prints a PDF (the WebView ignores window.print). Copies are the
document's pages repeated in one PDF, so the driver gets them in one job.
"""

from __future__ import annotations

import io

import frappe
from frappe import _
from frappe.utils import cint

PRINTABLE = ("Sales Invoice", "Payment Entry")
MAX_COPIES = 10


@frappe.whitelist(methods=["GET"])
def pdf(doctype: str, name: str, format: str | None = None, copies: int = 1, no_letterhead: int = 0):
    if doctype not in PRINTABLE:
        frappe.throw(_("Cannot print {0} from the app").format(doctype))
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("print")

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
