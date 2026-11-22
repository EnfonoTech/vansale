"""The branding the sign-in screen asks for before anyone is logged in
(`vansale.branding.get_branding`, `vansale.api.auth.branding`), without a site:
the Vansale Settings values come from a stub of `vansale.pwa._settings`.

Run: cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale \
     ../env/bin/python -m unittest vansale.tests.test_branding -v
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from vansale import branding


def settings(**values):
    """A stand-in for `vansale.pwa._settings()` (the Vansale Settings singles dict)."""
    return patch("vansale.pwa._settings", return_value=values)


class TestBranding(unittest.TestCase):
    def test_empty_settings(self):
        with settings():
            self.assertEqual(
                branding.get_branding(),
                {"app_name": "", "logo_url": "", "style": "classic"},
            )

    def test_name_is_stripped(self):
        with settings(pwa_app_name="  SF Connect "):
            self.assertEqual(branding.get_branding()["app_name"], "SF Connect")

    def test_login_logo_beats_app_icon(self):
        with settings(login_logo="/files/login.png", pwa_icon="/files/icon.png"):
            self.assertEqual(branding.get_branding()["logo_url"], "/files/login.png")

    def test_app_icon_is_the_fallback(self):
        with settings(pwa_icon="/files/icon.png"):
            self.assertEqual(branding.get_branding()["logo_url"], "/files/icon.png")

    def test_private_url_is_dropped(self):
        with settings(login_logo="/private/files/a.png", pwa_icon="/files/b.png"):
            self.assertEqual(branding.get_branding()["logo_url"], "/files/b.png")
        with settings(login_logo="/private/files/a.png", pwa_icon="/private/files/b.png"):
            self.assertEqual(branding.get_branding()["logo_url"], "")

    def test_style_map(self):
        for stored, expected in (
            ("Classic", "classic"),
            ("Split", "split"),
            ("Dark glass", "dark"),
            ("", "classic"),
            (None, "classic"),
            ("Neon", "classic"),
        ):
            with self.subTest(stored=stored):
                with settings(login_style=stored):
                    self.assertEqual(branding.get_branding()["style"], expected)

    def test_endpoint_is_guest_and_returns_the_same_values(self):
        from vansale.api import auth

        fn = auth.branding
        guest = frappe.guest_methods
        self.assertTrue(fn in guest or getattr(fn, "__wrapped__", None) in guest)
        # whitelisted functions are wrapped with an argument-type check that needs a request
        # context; the unwrapped function is the one under test
        call = getattr(fn, "__wrapped__", fn)
        with settings(pwa_app_name="SF Connect", login_style="Split"):
            self.assertEqual(call(), branding.get_branding())
            self.assertEqual(call()["style"], "split")


if __name__ == "__main__":
    unittest.main()
