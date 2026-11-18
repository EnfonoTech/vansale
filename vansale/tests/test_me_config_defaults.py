"""`vansale.api.me.config_defaults` without a site: the `is_system_manager`
key (the app keeps the van screens for a System Manager or Administrator who
has no van role or van configuration).

Run: cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale \
     ../env/bin/python -m unittest vansale.tests.test_me_config_defaults -v
"""

from __future__ import annotations

import types
import unittest

import frappe

from vansale.api import me
from vansale.tests.test_approvals_api import SiteFreeCase

_HELPERS = {
    "van_default": None,
    "user_to_sales_person": None,
    "global_flags": {"enable_route": True, "require_pin": True, "allow_uom_change": True},
    "amount_precision": 2,
    "rate_precision": 2,
    "cash_sale_settings": {"posting": "submit"},
    "split_payment_allowed": False,
    "advance_payment_allowed": False,
    "invoice_options": {},
    "return_without_invoice_allowed": False,
    "print_formats": {},
    "print_behaviour": {},
    "customer_form_config": {},
    "selling_flow": {},
}


class TestIsSystemManager(SiteFreeCase):
    def setUp(self):
        super().setUp()
        for name, value in _HELPERS.items():
            self._patch(f"vansale.api.me.{name}", return_value=value)
        self._patch("vansale.steelforce.approvals.is_available", return_value=False)
        self._patch("frappe.get_all", return_value=[])
        frappe.local.db.get_value.return_value = None  # no van configuration
        self.roles: list[str] = []
        self._patch("frappe.get_doc", side_effect=self._user)

    def _user(self, doctype, name=None, *args, **kwargs):
        self.assertEqual(doctype, "User")
        return types.SimpleNamespace(
            name=name,
            full_name=name,
            language="en",
            roles=[types.SimpleNamespace(role=role) for role in self.roles],
        )

    def _as(self, user: str, *roles: str) -> dict:
        frappe.local.session.user = user
        self.roles = list(roles)
        return me.config_defaults()

    def test_administrator_is_a_system_manager_even_without_the_role_row(self):
        self.assertIs(self._as("Administrator")["is_system_manager"], True)

    def test_a_user_with_the_system_manager_role_is_one(self):
        self.assertIs(self._as("it@example.com", "System Manager", "Employee")["is_system_manager"], True)

    def test_a_plain_van_user_is_not(self):
        defaults = self._as("ali@example.com", "Van User")

        self.assertIs(defaults["is_system_manager"], False)
        self.assertIs(defaults["is_van_user"], True)
        self.assertIsNone(defaults["van_code"])


if __name__ == "__main__":
    unittest.main()
