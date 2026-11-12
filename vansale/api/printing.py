"""Printing for the app.

`get_html`: the print format as desk's /printview renders it (format HTML, Print
Style and Frappe's print.bundle.css), so the in-app preview and web print
look the same as printing from desk.

`pdf`: the app's PDF (download, Android printing — the WebView ignores
window.print). Copies are the document's pages repeated in one PDF, so the
driver gets them in one job. With Vansale Settings "PDF same as browser
print" it is Chromium printing desk's print view, as Print → Save as PDF in
a browser does; Frappe's PDF engines lay pages out differently (wkhtmltopdf
has no flexbox; both force a 15 mm top margin and ignore the format's
@page rule).
"""

from __future__ import annotations

import io
import os
import subprocess
import tempfile

import frappe
from frappe import _
from frappe.utils import cint

from vansale.vansale.doctype.vansale_settings.vansale_settings import global_flags

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

    data = None
    if global_flags().get("pdf_like_browser_print"):
        data = _browser_print_pdf(doc, format, cint(no_letterhead))
    if data is None:
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


def _browser_print_pdf(doc, print_format: str | None, no_letterhead: int) -> bytes | None:
    """The PDF a browser makes from desk's print view (Print → Save as PDF):
    the same page printed by Chromium, so the format's @page size and margins
    apply. None when Chromium is missing or fails — the caller then uses
    Frappe's PDF, so printing keeps working."""
    from vansale.api.customer import _inline_public_images
    from vansale.pdf_engine import chromium_env, chromium_path

    exe = chromium_path()
    if not exe:
        frappe.log_error("Vansale: no Chromium for browser-print PDF", "Vansale PDF")
        return None
    html = frappe.get_print(doc.doctype, doc.name, print_format, doc=doc, no_letterhead=no_letterhead)
    # Images from the site's files go in the page itself; CSS and anything
    # else resolve against the site's URL.
    html = _inline_public_images(html)
    html = html.replace("<head>", f'<head><base href="{frappe.utils.get_url()}/">', 1)
    with tempfile.TemporaryDirectory(prefix="vansale-pdf-") as tmp:
        src, out = os.path.join(tmp, "doc.html"), os.path.join(tmp, "doc.pdf")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(html)
        try:
            subprocess.run(
                [
                    exe, "--headless", "--no-sandbox", "--disable-gpu",
                    "--no-pdf-header-footer", "--print-to-pdf-no-header",
                    f"--user-data-dir={os.path.join(tmp, 'profile')}",
                    f"--print-to-pdf={out}", "file://" + src,
                ],
                capture_output=True, timeout=60, check=False, env=chromium_env(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            frappe.log_error(f"{doc.doctype} {doc.name}: {exc}", "Vansale PDF")
            return None
        if not os.path.isfile(out) or os.path.getsize(out) == 0:
            frappe.log_error(f"{doc.doctype} {doc.name}: Chromium wrote no PDF", "Vansale PDF")
            return None
        with open(out, "rb") as fh:
            return fh.read()
