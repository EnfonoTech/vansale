"""The web app is served at /vansale and, as an alias, at /sf-connect: the install
files (manifest, service worker, icons) and the page's head tags follow the path
the app was opened at, so an installed /vansale app keeps working and a new
/sf-connect install is scoped to /sf-connect. No site needed.

Run: cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale \
     ../env/bin/python -m unittest vansale.tests.test_pwa_scope -v
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from vansale import hooks, pwa


class TestScopeOf(unittest.TestCase):
    def test_which_scope_a_path_belongs_to(self):
        for path, expected in (
            ("/sf-connect", "/sf-connect"),
            ("/sf-connect/login", "/sf-connect"),
            ("/sf-connect/manifest.webmanifest", "/sf-connect"),
            ("/vansale", "/vansale"),
            ("/vansale/approvals", "/vansale"),
            ("", "/vansale"),
            ("/", "/vansale"),
            ("/sf-connectx", "/vansale"),
            ("/app/sf-connect", "/vansale"),
        ):
            with self.subTest(path=path):
                self.assertEqual(pwa.scope_of(path), expected)


class TestScopedFiles(unittest.TestCase):
    def setUp(self):
        for target in ("vansale.pwa.app_name", "vansale.pwa.theme_color"):
            p = patch(target, return_value="SF Connect" if target.endswith("app_name") else "#2563eb")
            p.start()
            self.addCleanup(p.stop)

    def test_manifest_follows_the_scope(self):
        m = pwa._manifest("/sf-connect")
        self.assertEqual((m["id"], m["scope"], m["start_url"]), ("/sf-connect",) * 3)
        self.assertTrue(all(i["src"].startswith("/sf-connect/icon-") for i in m["icons"]))

    def test_manifest_default_is_still_vansale(self):
        m = pwa._manifest()
        self.assertEqual((m["id"], m["scope"], m["start_url"]), ("/vansale",) * 3)

    def test_head_tags_follow_the_scope(self):
        tags = pwa.head_tags("/sf-connect")
        self.assertIn('href="/sf-connect/manifest.webmanifest"', tags)
        self.assertIn('href="/sf-connect/icon-192.png"', tags)
        self.assertNotIn("/vansale/", tags)
        self.assertIn('href="/vansale/manifest.webmanifest"', pwa.head_tags())

    def test_worker_follows_the_scope(self):
        js = pwa.sw_js("/sf-connect")
        self.assertIn('const SHELL_URL = "/sf-connect";', js)
        self.assertIn('fetch("/sf-connect/shell-files.json"', js)
        self.assertIn('url.pathname.startsWith("/sf-connect/")', js)
        self.assertNotIn('"/vansale', js)
        # the built files are one set for both scopes
        self.assertIn("/assets/vansale/spa/", js)
        self.assertEqual(pwa.sw_js("/vansale"), pwa.SW_JS)


class TestRenderer(unittest.TestCase):
    def renderer(self, path):
        r = pwa.VansalePWARenderer.__new__(pwa.VansalePWARenderer)
        r.path = path
        return r

    def test_it_renders_the_install_files_of_both_scopes(self):
        for scope in ("/vansale", "/sf-connect"):
            for tail in ("manifest.webmanifest", "sw.js", "shell-files.json", "icon-192.png", "icon-512-maskable.png"):
                with self.subTest(path=f"{scope}/{tail}"):
                    self.assertTrue(self.renderer(f"{scope}/{tail}").can_render())

    def test_it_leaves_everything_else_to_the_page(self):
        for path in ("/sf-connect", "/sf-connect/login", "/sf-connect/icon-abc.png", "/sf-connect/extra/sw.js", "/other/sw.js"):
            with self.subTest(path=path):
                self.assertFalse(self.renderer(path).can_render())

    def test_worker_is_allowed_its_own_scope_only(self):
        for scope in ("/vansale", "/sf-connect"):
            with self.subTest(scope=scope):
                resp = self.renderer(f"{scope}/sw.js").render()
                self.assertEqual(resp.headers["Service-Worker-Allowed"], scope)
                self.assertIn(f'const SHELL_URL = "{scope}";', resp.get_data(as_text=True))


class TestRoutes(unittest.TestCase):
    def test_both_paths_render_the_app_page(self):
        rules = {(r["from_route"], r["to_route"]) for r in hooks.website_route_rules}
        for route in ("/vansale/<path:app_path>", "/sf-connect", "/sf-connect/<path:app_path>"):
            self.assertIn((route, "vansale"), rules)


if __name__ == "__main__":
    unittest.main()
