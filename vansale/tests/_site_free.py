"""Make a unit test run without a Frappe site.

`frappe.throw`, `frappe._` and `frappe.msgprint` read a handful of request
locals and one System Settings value; with no site connected those are
missing and the call fails with an `AttributeError` instead of raising the
error under test. `setup_site_free()` supplies them, `teardown_site_free()`
puts everything back, so the helper is also safe when the test module runs
under a real bench session.

    from vansale.tests import _site_free

    class TestSomething(unittest.TestCase):
        def setUp(self):
            _site_free.setup_site_free()
            self.addCleanup(_site_free.teardown_site_free)

Run site-free tests with the bench Python (the `vansale.steelforce` package
imports `frappe`) and from the `sites` folder:

    cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale \
        ../env/bin/python -m unittest <module> -v

`frappe.db` is a `LocalProxy` onto `frappe.local.db`, so a test that needs a
database stub sets `frappe.local.db` (done here with a `MagicMock`), never
patches `frappe.db` itself.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe

_MISSING = object()

_saved: dict = {}
_settings_patch = None


def setup_site_free() -> None:
    """Give `frappe.local` what `throw`/`msgprint`/`_` need. Calling it again
    without a teardown resets the values (a fresh message log) and keeps the
    originals saved by the first call."""
    global _settings_patch

    if _settings_patch is None:
        for attr in ("message_log", "flags", "lang", "session", "db"):
            _saved[attr] = getattr(frappe.local, attr, _MISSING)
        _settings_patch = patch("frappe.get_system_settings", return_value=None)
        _settings_patch.start()

    frappe.local.message_log = []
    frappe.local.flags = frappe._dict()
    frappe.local.lang = "en"
    frappe.local.session = frappe._dict(user="Administrator")
    frappe.local.db = MagicMock()


def teardown_site_free() -> None:
    """Undo `setup_site_free()`; does nothing when it was not called."""
    global _settings_patch

    if _settings_patch is None:
        return
    _settings_patch.stop()
    _settings_patch = None

    for attr, value in _saved.items():
        if value is _MISSING:
            try:
                delattr(frappe.local, attr)
            except AttributeError:
                pass
        else:
            setattr(frappe.local, attr, value)
    _saved.clear()
