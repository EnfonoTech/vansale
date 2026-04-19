"""Misc utilities whitelisted for the SPA."""

from __future__ import annotations

import frappe


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_csrf_token() -> str:
    """Return the CSRF token for the current session.

    Used by the web SPA to attach ``X-Frappe-CSRF-Token`` on POST calls.
    Capacitor APK uses token auth and skips this.
    """
    return frappe.sessions.get_csrf_token()


@frappe.whitelist(allow_guest=True, methods=["GET"])
def version_compat() -> dict:
    """Lightweight "is the SPA still compatible with this server?" probe.

    The SPA calls this on boot. If its ``NATIVE_VERSION`` falls below
    ``min``, it forces an update prompt.
    """
    # Values are intentionally strings so semver comparison works on device.
    return {
        "min": "1.0.0",
        "current": "1.0.0",
    }
