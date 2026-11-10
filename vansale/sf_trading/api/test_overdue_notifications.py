# apps/vansale/vansale/sf_trading/api/test_overdue_notifications.py
"""Tests for the overdue-invoice alert channels.

Read-only: nothing is emailed or pushed here — the tests exercise summary maths,
scope resolution, payload/digest building and the email guard. The email channel is
checked through ``_outgoing_email_configured()`` rather than by sending anything.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from vansale.sf_trading.api.overdue_notifications import (
    EMAIL_ROW_LIMIT,
    ROLE_SCOPE,
    _digest_html,
    _outgoing_email_configured,
    _overdue_summary,
    _payload,
    _top_overdue,
    _users_by_scope,
)


class TestOverdueNotifications(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.summary = _overdue_summary()

    def test_summary_shape(self):
        for scope in ("sales", "purchase"):
            self.assertIn(scope, self.summary)
            self.assertGreaterEqual(self.summary[scope]["count"], 0)
            self.assertGreaterEqual(self.summary[scope]["outstanding"], 0)

    def test_payload_scoping(self):
        both = _payload(self.summary, "both")
        sales = _payload(self.summary, "sales")
        purchase = _payload(self.summary, "purchase")

        if both is None:
            self.assertIsNone(sales)
            self.assertIsNone(purchase)
            return

        expected = (sales["count"] if sales else 0) + (purchase["count"] if purchase else 0)
        self.assertEqual(both["count"], expected)

        for payload in (both, sales, purchase):
            if not payload:
                continue
            for key in ("title", "message", "count", "outstanding", "currency", "report", "route"):
                self.assertIn(key, payload)

        # a purchase-scoped user must never be told about sales debt
        if purchase:
            self.assertNotIn("sales", purchase["message"])
        if sales:
            self.assertNotIn("purchase", sales["message"])

    def test_payload_none_when_nothing_overdue(self):
        empty = {"sales": {"count": 0, "outstanding": 0.0}, "purchase": {"count": 0, "outstanding": 0.0}}
        self.assertIsNone(_payload(empty, "both"))

    def test_users_by_scope_values(self):
        scopes = _users_by_scope()
        for user, scope in scopes.items():
            self.assertIn(scope, ("both", "sales", "purchase"))
            self.assertNotIn(user, ("Administrator", "Guest"))
            self.assertTrue(frappe.db.get_value("User", user, "enabled"))

    def test_role_scope_map_is_sane(self):
        self.assertEqual(set(ROLE_SCOPE.values()), {"both", "sales", "purchase"})

    def test_top_overdue_limit_and_order(self):
        rows = _top_overdue("both")
        self.assertLessEqual(len(rows), EMAIL_ROW_LIMIT)
        for row in rows:
            self.assertGreater(row["overdue_days"], 0)
        if len(rows) > 1:
            self.assertGreaterEqual(rows[0]["overdue_days"], rows[-1]["overdue_days"])

    def test_top_overdue_respects_scope(self):
        sales_rows = _top_overdue("sales")
        purchase_rows = _top_overdue("purchase")
        self.assertTrue(all(r["kind"] == "Sales" for r in sales_rows))
        self.assertTrue(all(r["kind"] == "Purchase" for r in purchase_rows))

    def test_digest_html_contains_rows_and_link(self):
        payload = _payload(self.summary, "both")
        if not payload:
            self.skipTest("nothing overdue on this site")
        rows = _top_overdue("both")
        html = _digest_html(payload, rows)

        self.assertIn("<table", html)
        self.assertIn("query-report", html)
        for row in rows[:3]:
            self.assertIn(row["invoice"], html)

    def test_email_guard_matches_email_account_state(self):
        """The guard must agree with the actual Email Account rows — email is optional."""
        self.assertEqual(
            _outgoing_email_configured(),
            bool(frappe.db.exists("Email Account", {"enable_outgoing": 1})),
        )
