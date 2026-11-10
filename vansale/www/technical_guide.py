# apps/vansale/vansale/www/technical_guide.py
"""Technical guide at /technical-guide.

Renders `docs/TECHNICAL_GUIDE.md` — the handbook for the client's own system administrator:
what they may configure in the live system, the steps, and where the line is.

The filename has to be `technical_guide.py`, with an underscore, even though the page is
`technical-guide.html`. Frappe builds the controller path by replacing hyphens with
underscores (`frappe/website/page_renderers/template_page.py`, `set_pymodule`), so a
hyphenated controller is never imported at all — and a permission check inside one that is
never imported silently does nothing while the page still serves happily.

Unlike the feature guide at /user-guide, this one needs a login. It is a map of how the live
system is put together, which is not something to leave on the open internet. Guests get a 403
with a login link rather than a redirect.
"""

import os

import frappe
from frappe import _

# the guide is regenerated from the file on every request; nothing here is worth caching
no_cache = 1


def get_context(context):
    if frappe.session.user == "Guest":
        raise frappe.PermissionError(_("Please log in to read the technical guide."))

    context.title = _("Technical Guide")
    context.guide_html = render_guide()
    # computed here rather than in the template: frappe.utils is not exposed to the website
    # Jinja context, and calling it there truncates everything after that point
    context.updated_on = frappe.utils.formatdate(frappe.utils.nowdate(), "d MMMM yyyy")
    return context


def render_guide():
    """The markdown, rendered the same way the feature guide is.

    Imported rather than copied so the two pages can never format the same markdown
    differently — the table wrapping in particular is what keeps a wide table scrolling
    instead of crushing its columns.
    """
    from vansale.www.user_guide import strip_manual_toc, wrap_tables

    path = os.path.join(frappe.get_app_source_path("vansale"), "docs", "sf_trading", "TECHNICAL_GUIDE.md")
    if not os.path.isfile(path):
        return "<p>%s</p>" % _("The technical guide file is missing on this server.")

    with open(path, encoding="utf-8") as handle:
        markdown = handle.read()

    return wrap_tables(frappe.utils.md_to_html(strip_manual_toc(markdown)))
