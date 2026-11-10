# apps/vansale/vansale/www/user-guide.py
"""Public user guide at /user-guide.

Renders `docs/sf_trading/USER_GUIDE.md` — the same file the desk page
`sf-trading-user-guide` shows — so the two surfaces can never drift apart. No login required.
"""

import os
import re

import frappe

no_cache = 1

TOC_HEADING = "## Table of Contents"


def get_context(context):
    context.title = "SF Trading User Guide"
    context.guide_html = render_guide()
    # computed here, not in the template: `frappe.utils` is not exposed to the website Jinja
    # context, and calling it there silently truncates everything after that point
    context.updated_on = frappe.utils.formatdate(frappe.utils.nowdate(), "d MMMM yyyy")
    return context


def strip_manual_toc(markdown):
    """Drop the hand-written table of contents.

    It exists so the file reads well on GitHub; both rendered surfaces build their own index
    from the headings, so keeping it would print the list twice.
    """
    if TOC_HEADING not in markdown:
        return markdown

    before, _, rest = markdown.partition(TOC_HEADING)
    next_heading = rest.find("\n## ")
    return before + (rest[next_heading:] if next_heading != -1 else "")


def render_guide():
    path = os.path.join(frappe.get_app_source_path("vansale"), "docs", "sf_trading", "USER_GUIDE.md")
    if not os.path.isfile(path):
        return "<p>%s</p>" % frappe._("The user guide file is missing on this server.")

    with open(path, encoding="utf-8") as handle:
        markdown = handle.read()

    from vansale.sf_trading.api.user_guide_screens import screens_markdown

    markdown = strip_manual_toc(markdown) + screens_markdown()
    return wrap_tables(frappe.utils.md_to_html(markdown))


def wrap_tables(html):
    """Put every table in a scroll container.

    A payables table with six columns has nowhere to go on a laptop screen, and the guide is
    table-heavy. Wrapping server-side keeps the markdown clean and lets CSS handle the rest.
    """
    return re.sub(
        r"<table(.*?)</table>",
        lambda m: '<div class="table-wrap"><table%s</table></div>' % m.group(1),
        html,
        flags=re.S,
    )
