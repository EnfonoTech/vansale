"""Install / migrate hooks.

`ensure_capacitor_cors()` is the single place that wires Capacitor origins
into `site_config.json.allow_cors`. Without it every APK request fails at
preflight with a silent "Failed to fetch" — the Frappe request log never
records the attempt. See `frappe-vue-pwa` §3.6.
"""

import json
import os

import frappe

CAPACITOR_ORIGINS = [
    "https://localhost",
    "capacitor://localhost",
    "http://localhost",
]


def ensure_capacitor_cors() -> None:
    path = frappe.get_site_path("site_config.json")
    if not os.path.exists(path):
        return

    with open(path) as fh:
        cfg = json.load(fh)

    current = cfg.get("allow_cors")
    if current == "*":
        return

    if not isinstance(current, list):
        current = []

    changed = False
    for origin in CAPACITOR_ORIGINS:
        if origin not in current:
            current.append(origin)
            changed = True

    if changed:
        cfg["allow_cors"] = current
        with open(path, "w") as fh:
            json.dump(cfg, fh, indent=1)
