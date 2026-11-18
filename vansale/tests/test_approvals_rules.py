"""Pure rules behind the Approvals screen: action tone, what an action must be
given, whether an apply may go ahead, the area filter and the two inbox stats.

The rules module imports no `frappe`, so nothing here needs a site.

Run: cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale \
     ../env/bin/python -m unittest vansale.tests.test_approvals_rules -v
"""

from __future__ import annotations

import unittest

from vansale.steelforce.approvals_rules import (
    area_of,
    check_apply,
    inbox_stats,
    required_inputs,
    tone_of,
)


def _spec(**flags) -> dict:
    spec = {
        "action": "Approve",
        "require_comment": False,
        "require_attachment": False,
        "is_return_for_correction": False,
        "recommend_only": False,
    }
    spec.update(flags)
    return spec


class TestToneOf(unittest.TestCase):
    def test_approving_actions(self):
        for action in ("Approve", "Send for Approval", "Accept", "Approve Cancellation"):
            with self.subTest(action=action):
                self.assertEqual(tone_of(action, False), "approve")

    def test_reject_by_name(self):
        self.assertEqual(tone_of("Reject Cancellation", False), "reject")
        self.assertEqual(tone_of("reject", False), "reject")

    def test_return_for_correction_is_always_reject(self):
        self.assertEqual(tone_of("Reject", True), "reject")
        self.assertEqual(tone_of("Anything", True), "reject")

    def test_request_is_other(self):
        self.assertEqual(tone_of("Request Cancellation", False), "other")


class TestRequiredInputs(unittest.TestCase):
    def test_return_for_correction_needs_a_comment_only(self):
        self.assertEqual(
            required_inputs(False, False, True, False),
            {"comment": True, "attachment": False},
        )

    def test_require_comment(self):
        self.assertIs(required_inputs(True, False, False, False)["comment"], True)

    def test_nothing_required(self):
        self.assertEqual(
            required_inputs(False, False, False, False),
            {"comment": False, "attachment": False},
        )

    def test_attachment_required_until_the_document_has_one(self):
        self.assertIs(required_inputs(False, True, False, False)["attachment"], True)
        self.assertIs(required_inputs(False, True, False, True)["attachment"], False)


class TestCheckApply(unittest.TestCase):
    def test_no_spec_means_not_allowed(self):
        self.assertEqual(check_apply(None, "x", True), "not_allowed")

    def test_plain_approve_is_allowed(self):
        self.assertIsNone(check_apply(_spec(), None, False))
        self.assertIsNone(check_apply(_spec(), "", False))

    def test_return_for_correction_needs_a_real_comment(self):
        spec = _spec(action="Reject", is_return_for_correction=True)
        self.assertEqual(check_apply(spec, "  ", False), "comment_required")
        self.assertEqual(check_apply(spec, None, False), "comment_required")
        self.assertIsNone(check_apply(spec, "wrong rate", False))

    def test_require_comment_is_enforced(self):
        spec = _spec(require_comment=True)
        self.assertEqual(check_apply(spec, "", False), "comment_required")
        self.assertIsNone(check_apply(spec, "ok", False))

    def test_attachment_required_when_the_document_has_none(self):
        spec = _spec(require_attachment=True)
        self.assertEqual(check_apply(spec, "", False), "attachment_required")
        self.assertIsNone(check_apply(spec, "", True))

    def test_comment_is_checked_before_attachment(self):
        spec = _spec(require_comment=True, require_attachment=True)
        self.assertEqual(check_apply(spec, "", False), "comment_required")
        self.assertEqual(check_apply(spec, "ok", False), "attachment_required")

    def test_recommend_only_asks_for_nothing(self):
        spec = _spec(
            recommend_only=True,
            require_comment=True,
            require_attachment=True,
            is_return_for_correction=True,
        )
        self.assertIsNone(check_apply(spec, None, False))


class TestAreaOf(unittest.TestCase):
    def test_areas(self):
        expected = {
            "Journal Entry": "Accounts",
            "Payment Entry": "Accounts",
            "Payment Advice": "Accounts",
            "Payment Request": "Accounts",
            "Purchase Invoice": "Purchase",
            "Purchase Order": "Purchase",
            "Purchase Receipt": "Purchase",
            "Sales Invoice": "Sales",
            "Sales Order": "Sales",
            "Quotation": "Sales",
            "Delivery Note": "Sales",
            "Customer": "Masters",
            "Supplier": "Masters",
            "Item": "Masters",
            "SF Master Change Request": "Masters",
            "Stock Reconciliation": "Stock",
            "Material Request": "Stock",
            "Stock Entry": "Stock",
        }
        for doctype, area in expected.items():
            with self.subTest(doctype=doctype):
                self.assertEqual(area_of(doctype), area)

    def test_unknown_doctype_is_other(self):
        self.assertEqual(area_of("Something Else"), "Other")
        self.assertEqual(area_of(""), "Other")


class TestInboxStats(unittest.TestCase):
    def test_high_and_critical_count_and_overdue_is_over_thirty_days(self):
        items = [
            {"days": 30, "priority": "High"},
            {"days": 31, "priority": "Critical"},
            {"days": 5, "priority": "Low"},
        ]
        self.assertEqual(inbox_stats(items), {"high": 2, "overdue": 1})

    def test_empty_inbox(self):
        self.assertEqual(inbox_stats([]), {"high": 0, "overdue": 0})

    def test_medium_is_not_high_and_missing_days_is_not_overdue(self):
        items = [{"days": None, "priority": "Medium"}, {"priority": "Medium"}]
        self.assertEqual(inbox_stats(items), {"high": 0, "overdue": 0})


if __name__ == "__main__":
    unittest.main()
