"""Serve the SPA at /vansale (and every /vansale/<path>, see hooks.py).

Browser-history routing needs the app's index.html at its own URL, so a
refresh on /vansale/invoices loads the app instead of a 404. The built
assets keep their /assets/vansale/spa/ URLs.
"""

import os

import frappe

no_cache = 1


def get_context(context):
    context.no_cache = 1
    _leave_site_root()
    index_path = frappe.get_app_path("vansale", "public", "spa", "index.html")
    if os.path.exists(index_path):
        from vansale.pwa import head_tags

        with open(index_path, encoding="utf-8") as fh:
            # Manifest + icons, so phones offer "Install app" (see vansale/pwa.py).
            context.spa_html = fh.read().replace("</head>", head_tags() + "</head>", 1)
    else:
        context.spa_html = "<h1>Van Sale is not built. Run the frontend build.</h1>"


def _leave_site_root() -> None:
    """The site root (/) is rendered with this page for anyone holding a Van
    role (hooks.py role_home_page). Administrator holds every role, so the
    desk's own root showed the van app's login. Send desk admins to the desk,
    and van users to the app's own URL (it routes from there)."""
    path = (frappe.request.path if getattr(frappe, "request", None) else "/vansale").strip("/")
    if path not in ("", "index"):
        return
    user = frappe.session.user
    desk_admin = user == "Administrator" or "System Manager" in frappe.get_roles(user)
    frappe.local.flags.redirect_location = "/app" if desk_admin else "/vansale"
    # 302: the answer depends on who is logged in, so no browser may keep it.
    raise frappe.Redirect(302)
