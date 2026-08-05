#!/usr/bin/env python3
"""Capture the user-guide screenshots with Playwright.

Sessions are minted SERVER-SIDE (frappe.sessions.Session) and injected as `sid`
cookies — no password is ever typed or stored here. Pass them in:

    SID_ADMIN=... SID_VAN=... python3 scripts/capture-screenshots.py

App screens are captured from the web PWA at a phone viewport; it is the same Vue
source as the APK. The app keeps its own session in localStorage, so that is
seeded to match the cookie — the API still authenticates by cookie.

Two shots cannot come from here and stay as wireframes: the Android print sheet
and the GPS permission prompt are native OS surfaces.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

SITE = os.environ.get("SITE", "https://trading-demo.enfonoerp.com")
SID_ADMIN = os.environ.get("SID_ADMIN", "")
SID_VAN = os.environ.get("SID_VAN", "")
VAN_USER = os.environ.get("VAN_USER", "vanuser@gmail.com")
VAN_NAME = os.environ.get("VAN_NAME", "Van 001")

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "userguide" / "img"
SPA = f"{SITE}/assets/vansale/spa/index.html"
PHONE = {"width": 390, "height": 844}
DESK = {"width": 1440, "height": 900}

# App session as the SPA expects it. pinVerifiedAt is now so the PIN gate is
# already satisfied; the PIN screen gets its own seed below.
def session_blob(pin_verified_ms: int | None, require_pin: bool) -> str:
    return json.dumps({
        "user": VAN_USER,
        "fullName": VAN_NAME,
        "email": VAN_USER,
        "language": "en",
        "pinVerifiedAt": pin_verified_ms,
        "defaults": None,
        "requirePin": require_pin,
    })


def seed(page, blob: str) -> None:
    page.add_init_script(
        f"""try {{
              localStorage.setItem('vansale.session', {json.dumps(blob)});
              localStorage.setItem('vansale.siteUrl', {json.dumps(SITE)});
            }} catch (e) {{}}"""
    )


def shot(page, n: int, hash_route: str, wait_for: str | None = None, settle: float = 2.2) -> None:
    page.goto(f"{SPA}#{hash_route}", wait_until="domcontentloaded")
    if wait_for:
        try:
            page.wait_for_selector(wait_for, timeout=12000)
        except Exception:
            print(f"  !! shot {n:02d}: selector {wait_for!r} never appeared")
    time.sleep(settle)
    path = OUT / f"shot-{n:02d}.png"
    page.screenshot(path=str(path))
    print(f"  shot-{n:02d}.png  {hash_route or '/'}  ({path.stat().st_size // 1024} KB)")


def desk_shot(page, n: int, url: str, settle: float = 3.0, full: bool = False) -> None:
    page.goto(url, wait_until="domcontentloaded")
    time.sleep(settle)
    path = OUT / f"shot-{n:02d}.png"
    page.screenshot(path=str(path), full_page=full)
    print(f"  shot-{n:02d}.png  {url.split(SITE)[-1]}  ({path.stat().st_size // 1024} KB)")


def main() -> None:
    if not (SID_ADMIN and SID_VAN):
        sys.exit("SID_ADMIN and SID_VAN are required")
    OUT.mkdir(parents=True, exist_ok=True)
    host = SITE.split("://", 1)[1]

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # ---------------------------------------------------- app, logged out --
        ctx = browser.new_context(viewport=PHONE, device_scale_factor=2)
        page = ctx.new_page()
        shot(page, 2, "/login", wait_for="input[type=email]")
        ctx.close()

        # ---------------------------------------------------- app, van user ----
        ctx = browser.new_context(viewport=PHONE, device_scale_factor=2)
        ctx.add_cookies([{"name": "sid", "value": SID_VAN, "domain": host, "path": "/"}])
        page = ctx.new_page()
        seed(page, session_blob(int(time.time() * 1000), True))

        shot(page, 3, "/", wait_for=".dashboard")
        shot(page, 4, "/invoice/new", wait_for=".catalog", settle=3.0)
        shot(page, 8, "/route", settle=2.6)
        shot(page, 9, "/sync", settle=2.2)
        shot(page, 10, "/more", settle=2.2)
        shot(page, 6, "/payment/new", settle=2.6)

        # Sales list, then the newest submitted invoice for the detail shot.
        shot(page, 5, "/invoices", wait_for=None, settle=2.6)
        ctx.close()

        # PIN unlock needs a stale window so the guard routes to /pin in
        # "unlock" mode rather than first-time setup.
        ctx = browser.new_context(viewport=PHONE, device_scale_factor=2)
        ctx.add_cookies([{"name": "sid", "value": SID_VAN, "domain": host, "path": "/"}])
        page = ctx.new_page()
        stale = int((time.time() - 3 * 3600) * 1000)
        seed(page, session_blob(stale, True))
        shot(page, 7, "/pin", wait_for=".pin-card", settle=1.8)
        ctx.close()

        # -------------------------------------------------------- desk shots --
        ctx = browser.new_context(viewport=DESK, device_scale_factor=2)
        ctx.add_cookies([{"name": "sid", "value": SID_ADMIN, "domain": host, "path": "/"}])
        page = ctx.new_page()
        desk_shot(page, 11, f"{SITE}/app/vansale", settle=4.5)
        desk_shot(page, 12, f"{SITE}/app/vansale-settings", settle=4.0)
        desk_shot(page, 13, f"{SITE}/app/vansale-configuration/VAB-AB-001", settle=4.5)
        desk_shot(page, 14, f"{SITE}/app/query-report/Van%20Daily%20Settlement", settle=6.0)
        ctx.close()
        browser.close()

    print(f"\n{len(list(OUT.glob('shot-*.png')))} screenshots in {OUT}")


if __name__ == "__main__":
    main()
