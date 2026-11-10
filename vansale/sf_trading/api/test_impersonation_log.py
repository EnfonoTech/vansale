# apps/vansale/vansale/sf_trading/api/test_impersonation_log.py
"""Tests for the impersonation-reason hook.

Nothing is inserted: the hook is a ``before_insert`` mutator, so the tests build an
unsaved Activity Log, fake the request that would be carrying the reason, and check
what the hook wrote onto the row.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from vansale.sf_trading.api.impersonation_log import (
    REASON_FIELD,
    SUBJECT_REASON_LIMIT,
    capture_impersonation_reason,
)

BASE_SUBJECT = "User Administrator impersonated as ramees.pm@steelforceco.com"


class TestImpersonationLog(FrappeTestCase):
    def setUp(self):
        self._form_dict = frappe.local.form_dict

    def tearDown(self):
        frappe.local.form_dict = self._form_dict

    def _log(self, operation="Impersonate", subject=BASE_SUBJECT):
        return frappe.get_doc(
            {
                "doctype": "Activity Log",
                "user": "Administrator",
                "status": "Success",
                "subject": subject,
                "operation": operation,
            }
        )

    def _request(self, **args):
        frappe.local.form_dict = frappe._dict(args)

    def test_reason_lands_on_the_row(self):
        self._request(user="ramees.pm@steelforceco.com", reason="Checking a stuck PO approval")
        doc = self._log()

        capture_impersonation_reason(doc)

        self.assertEqual(doc.get(REASON_FIELD), "Checking a stuck PO approval")
        self.assertIn("Checking a stuck PO approval", doc.subject)
        self.assertIn(BASE_SUBJECT, doc.subject)
        self.assertIn("Checking a stuck PO approval", doc.content)

    def test_login_rows_are_untouched(self):
        self._request(reason="Checking a stuck PO approval")
        doc = self._log(operation="Login", subject="Administrator")

        capture_impersonation_reason(doc)

        self.assertEqual(doc.subject, "Administrator")
        self.assertFalse(doc.get(REASON_FIELD))
        self.assertFalse(doc.get("content"))

    def test_no_reason_leaves_the_subject_alone(self):
        self._request(user="ramees.pm@steelforceco.com")
        doc = self._log()

        capture_impersonation_reason(doc)

        self.assertEqual(doc.subject, BASE_SUBJECT)
        self.assertFalse(doc.get(REASON_FIELD))

    def test_blank_reason_is_ignored(self):
        self._request(reason="   ")
        doc = self._log()

        capture_impersonation_reason(doc)

        self.assertEqual(doc.subject, BASE_SUBJECT)
        self.assertFalse(doc.get(REASON_FIELD))

    def test_markup_is_stripped(self):
        self._request(reason="<b>debug</b> the invoice")
        doc = self._log()

        capture_impersonation_reason(doc)

        self.assertEqual(doc.get(REASON_FIELD), "debug the invoice")
        self.assertNotIn("<b>", doc.subject)
        self.assertNotIn("<b>", doc.content)

    def test_long_reason_is_trimmed_in_the_subject_only(self):
        reason = "a" * (SUBJECT_REASON_LIMIT + 50)
        self._request(reason=reason)
        doc = self._log()

        capture_impersonation_reason(doc)

        # the field keeps everything, the subject carries a shortened copy
        self.assertEqual(doc.get(REASON_FIELD), reason)
        self.assertIn("…", doc.subject)
        self.assertLess(len(doc.subject), len(BASE_SUBJECT) + len(reason))

    def test_existing_content_is_preserved(self):
        self._request(reason="Checking a stuck PO approval")
        doc = self._log()
        doc.content = "written by something else"

        capture_impersonation_reason(doc)

        self.assertEqual(doc.content, "written by something else")
        self.assertEqual(doc.get(REASON_FIELD), "Checking a stuck PO approval")
