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
    index_path = frappe.get_app_path("vansale", "public", "spa", "index.html")
    if os.path.exists(index_path):
        from vansale.pwa import head_tags

        with open(index_path, encoding="utf-8") as fh:
            # Manifest + icons, so phones offer "Install app" (see vansale/pwa.py).
            context.spa_html = fh.read().replace("</head>", head_tags() + "</head>", 1)
    else:
        context.spa_html = "<h1>Van Sale is not built. Run the frontend build.</h1>"
