# apps/vansale/vansale/sf_trading/report/pdc_report/test_pdc_report.py
"""Tests for the PDC Report.

Read-only against live data: the report never writes. The point of these tests is the
reminder anchor — the report's Reminder Date column and the "PDC Cheque Date Reminder"
notification must count back from the same field (`posting_date`) by the same number of
days, or an accountant reads one date in the report and gets the alert on another.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, date_diff, getdate, nowdate

from vansale.sf_trading.report.pdc_report.pdc_report import (
    REMINDER_LEAD_DAYS,
    execute,
    get_cheque_modes,
)

NOTIFICATION = "PDC Cheque Date Reminder"


class TestPDCReport(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
            "Company", {}, "name"
        )

    def _run(self, **filters):
        base = {"company": self.company, "include_cancelled": 1}
        base.update(filters)
        return execute(base)

    def test_columns_expose_the_posting_date_and_its_reminder(self):
        columns, _rows = self._run()
        fieldnames = [c["fieldname"] for c in columns]
        for expected in ("posting_date", "reminder_date", "days_to_posting_date", "cheque_date"):
            self.assertIn(expected, fieldnames)
        # posting date sits with the reminder it drives, not at the far right of the report
        self.assertLess(fieldnames.index("posting_date"), fieldnames.index("cheque_date"))

    def test_reminder_date_counts_back_from_the_posting_date(self):
        _columns, rows = self._run()
        for row in rows:
            if not row["posting_date"]:
                self.assertIsNone(row["reminder_date"])
                continue
            self.assertEqual(
                getdate(row["reminder_date"]),
                add_days(getdate(row["posting_date"]), -REMINDER_LEAD_DAYS),
            )

    def test_days_to_posting_date_is_measured_from_today(self):
        _columns, rows = self._run()
        today = getdate(nowdate())
        for row in rows:
            if row["posting_date"]:
                self.assertEqual(row["days_to_posting_date"], date_diff(getdate(row["posting_date"]), today))

    def test_only_cheque_modes_are_reported(self):
        modes = get_cheque_modes()
        _columns, rows = self._run()
        for row in rows:
            self.assertIn(row["mode_of_payment"], modes)

    def test_notification_anchors_on_the_same_field_and_lead(self):
        """The report column exists to predict this notification — keep them in step."""
        if not frappe.db.exists("Notification", NOTIFICATION):
            self.skipTest(f"{NOTIFICATION} is not installed on this site")

        notification = frappe.db.get_value(
            "Notification", NOTIFICATION, ["event", "date_changed", "days_in_advance"], as_dict=True
        )
        self.assertEqual(notification.event, "Days Before")
        self.assertEqual(notification.date_changed, "posting_date")
        self.assertEqual(notification.days_in_advance, REMINDER_LEAD_DAYS)

    def test_status_filter_splits_cleared_from_pending(self):
        _columns, pending = self._run(status="Pending", include_cancelled=0)
        for row in pending:
            self.assertIsNone(row["clearance_date"])
            self.assertEqual(row["status"], "Pending")

        _columns, cleared = self._run(status="Cleared", include_cancelled=0)
        for row in cleared:
            self.assertTrue(row["clearance_date"])
            self.assertEqual(row["status"], "Cleared")
