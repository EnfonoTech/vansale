"""The parity report (`vansale.steelforce.approvals_parity`) without a site and
without `permission_manager` (PM): every PM call goes through `approvals._pm()`,
which these tests replace, and every `get_all` answers from tables the test
writes down, applying the filters it is given (so a filter that is missing or
wrong changes the answer and a test fails).

Two kinds of test. The first kind replaces the four PWA endpoints (`inbox`,
`count`, `sent_back`, `my_requests`) to show what each comparison reports. The
second runs the real endpoints against the same PM stub, so the report is also
checked against the shapes they really return.

Run: cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale \
     ../env/bin/python -m unittest vansale.tests.test_approvals_parity -v
"""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, call

import frappe

from vansale.steelforce import approvals, approvals_parity
from vansale.tests.test_approvals_api import ME, SiteFreeCase, pm_item, pm_pending, pm_waiting

RUNNER = "dev@example.com"
"""Who runs the report (the console user); the report must hand the session
back to them."""
OTHER = "omar@example.com"
PM_ACTION = approvals.PM_ACTION
PM_ROLE = "PM Workflow Action Permitted Role"

KEYS = {
    "user",
    "desk_total",
    "pwa_total",
    "desk_waiting",
    "pwa_waiting",
    "needs_you",
    "sent_back_equal",
    "my_requests_equal",
    "ok",
    "differences",
    "skipped",
}


# ─── the world the stubs describe ─────────────────────────────────────────────


def inbox_of(pending: dict) -> dict:
    """What `approvals.inbox()` answers for PM's `pending` answer."""
    items = [item for group in pending["groups"] for item in group["items"]]
    needs_you = [item for item in items if not item["is_waiting"]]
    waiting = [item for item in items if item["is_waiting"]]
    sections: dict[str, list] = {}
    for item in needs_you:
        sections.setdefault(item["category"], []).append({"action_id": item["name"]})
    return {
        "total": pending["total"],
        "needs_you": pending["total"] - len(waiting),
        "waiting": len(waiting),
        "stats": {"high": 0, "overdue": 0},
        "sections": [{"category": label, "items": rows} for label, rows in sections.items()],
        "waiting_items": [{"action_id": item["name"]} for item in waiting],
        "fetched_at": "2026-11-19T04:00:00Z",
    }


def count_of(pending: dict) -> dict:
    """What `approvals.count()` answers for PM's `pending` answer."""
    inbox = inbox_of(pending)
    return {key: inbox[key] for key in ("total", "needs_you", "waiting")} | {"high": 0, "overdue": 0}


def sent_back_row(docname: str, doctype: str = "Sales Invoice", **overrides) -> dict:
    row = {
        "doctype": doctype,
        "transaction": doctype,
        "docname": docname,
        "state": "Rejected",
        "sent_back_by": "Omar Saleh",
        "sent_back_on": datetime(2026, 11, 16, 9, 30, 45),
        "role": "Finance Head",
        "reason": "Wrong customer",
    }
    row.update(overrides)
    return row


def request_item(docname: str, doctype: str = "Sales Invoice") -> dict:
    """A row of `my_requests()["items"]`."""
    return {"doctype": doctype, "docname": docname, "state": "Pending Finance", "days": 3}


def action_row(name: str, doctype: str, docname: str, **overrides) -> dict:
    """A PM Workflow Action: sara's own submission, still open."""
    row = {
        "name": name,
        "reference_doctype": doctype,
        "reference_name": docname,
        "for_submitter": ME,
        "status": "Open",
        "is_adhoc": 0,
        "assigned_to": None,
        "workflow_state": "Pending Finance",
        "priority": "Medium",
        "creation": datetime(2026, 11, 10, 9, 30),
    }
    row.update(overrides)
    return row


class Tables:
    """A stand-in for `frappe.get_all` that answers from `rows[doctype]`,
    applying the filters it is given (equality, `in`, `not in`, `!=`), and fails
    on a doctype it was not given. `.calls` lists `(doctype, kwargs)`."""

    def __init__(self):
        self.rows: dict[str, list[dict]] = {}
        self.calls: list = []

    def __call__(self, doctype, *args, filters=None, pluck=None, **kwargs):
        self.calls.append((doctype, {"filters": filters, "pluck": pluck, **kwargs}))
        if doctype not in self.rows:
            raise AssertionError(f"unexpected get_all({doctype!r}, {filters})")
        rows = [row for row in self.rows[doctype] if self._matches(row, filters or {})]
        if pluck:
            return [row[pluck] for row in rows]
        return [frappe._dict(row) for row in rows]

    @staticmethod
    def _matches(row: dict, filters: dict) -> bool:
        for field, wanted in filters.items():
            value = row.get(field)
            if not isinstance(wanted, list):
                ok = value == wanted
            elif wanted[0] == "in":
                ok = value in wanted[1]
            elif wanted[0] == "not in":
                ok = value not in wanted[1]
            elif wanted[0] == "!=":
                ok = value != wanted[1]
            else:
                raise AssertionError(f"unexpected filter {field}: {wanted}")
            if not ok:
                return False
        return True

    def of(self, doctype: str) -> list[dict]:
        return [kwargs for name, kwargs in self.calls if name == doctype]


def my_world() -> dict[str, list[dict]]:
    """sara's two real requests among everything else a read must leave out."""
    return {
        PM_ACTION: [
            action_row("WA-10", "Sales Invoice", "SINV-1"),
            # a second action on the same document: still one request
            action_row("WA-11", "Sales Invoice", "SINV-1", status="Forwarded"),
            action_row("WA-12", "Purchase Invoice", "PINV-1", status="Forwarded"),
            # decided already
            action_row("WA-13", "Sales Invoice", "SINV-2", status="Completed"),
            action_row("WA-14", "Sales Invoice", "SINV-6", status="Reassigned"),
            # somebody else's
            action_row("WA-15", "Sales Invoice", "SINV-3", for_submitter=OTHER),
            # types the approvals never handle
            action_row("WA-16", "Stock Entry", "STE-1"),
            action_row("WA-17", "Gate Pass", "GP-1"),
            # cancelled, and deleted (no row below)
            action_row("WA-18", "Sales Invoice", "SINV-4"),
            action_row("WA-19", "Sales Invoice", "SINV-5"),
        ],
        "Sales Invoice": [
            {"name": name, "docstatus": status}
            for name, status in (
                ("SINV-1", 1), ("SINV-2", 1), ("SINV-3", 1), ("SINV-4", 2), ("SINV-6", 1)
            )
        ],
        "Purchase Invoice": [{"name": "PINV-1", "docstatus": 1}],
        "Stock Entry": [{"name": "STE-1", "docstatus": 1}],
        "Gate Pass": [{"name": "GP-1", "docstatus": 1}],
    }  # fmt: skip


MY_REQUESTS = [("Sales Invoice", "SINV-1"), ("Purchase Invoice", "PINV-1")]
"""What `my_world()` holds for sara once the noise is left out."""


# ─── the report against stubbed endpoints ─────────────────────────────────────


class ParityCase(SiteFreeCase):
    """The console user is `RUNNER`; the report is run for sara. Every source
    answers from the attributes below, read when it is called, so a test sets
    what it wants before running the report; `ran_as` records who the session
    was for each call."""

    def setUp(self):
        super().setUp()
        frappe.local.session.user = RUNNER
        frappe.local.db.exists.return_value = ME
        self.ran_as: dict[str, str] = {}
        self._patch("vansale.steelforce.approvals.is_available", return_value=True)
        self.pm = MagicMock(name="pm")
        self.pm.hidden_doctypes.return_value = ["Gate Pass"]
        self._patch("vansale.steelforce.approvals._pm", return_value=self.pm)
        self.set_user = self._patch("frappe.set_user", side_effect=self._set_user)

        # PM's own answers
        self.pending = pm_pending(
            pm_item("WA-1"),
            pm_item("WA-2", doctype="Purchase Invoice", docname="PINV-7", category="Decision Pending"),
            pm_waiting("WA-3"),
        )
        self.sent_back_rows = [sent_back_row("SINV-9"), sent_back_row("PINV-4", "Purchase Invoice")]
        self.pm.get_my_pending_approvals.side_effect = self._recorded("pm pending", lambda: self.pending)
        self.pm.get_sent_back_documents.side_effect = self._recorded(
            "pm sent back", lambda: list(self.sent_back_rows)
        )

        # the PWA's answers (equal to PM's until a test changes one)
        self.pwa_inbox = inbox_of(self.pending)
        self.pwa_count = count_of(self.pending)
        self.pwa_sent_back = [dict(row) for row in self.sent_back_rows]
        self.pwa_requests = [request_item(name, doctype) for doctype, name in MY_REQUESTS]
        self.inbox = self._source("inbox", "approvals.inbox", lambda: self.pwa_inbox)
        self.count = self._source("count", "approvals.count", lambda: self.pwa_count)
        self.sent_back = self._source(
            "sent_back", "approvals_extra.sent_back", lambda: {"items": self.pwa_sent_back}
        )
        self.my_requests = self._source(
            "my_requests", "approvals_extra.my_requests", lambda: {"items": self.pwa_requests}
        )

        # the independent read of sara's requests
        self.tables = Tables()
        self.tables.rows = my_world()
        self.get_all = self._patch("frappe.get_all", side_effect=self._read)

    def _set_user(self, user):
        frappe.local.session.user = user

    def _recorded(self, name: str, make):
        def run(*args, **kwargs):
            self.ran_as[name] = frappe.session.user
            return make()

        return run

    def _source(self, name: str, target: str, make):
        return self._patch(f"vansale.steelforce.{target}", side_effect=self._recorded(name, make))

    def _read(self, *args, **kwargs):
        self.ran_as["get_all"] = frappe.session.user
        return self.tables(*args, **kwargs)

    def report(self, user: str = ME) -> dict:
        return approvals_parity.parity_report(user)

    def fields(self, report: dict) -> list[str]:
        return [difference["field"] for difference in report["differences"]]


class TestEqualInputs(ParityCase):
    def test_the_report_is_ok_and_says_what_it_compared(self):
        self.assertEqual(
            self.report(),
            {
                "user": ME,
                "desk_total": 3,
                "pwa_total": 3,
                "desk_waiting": 1,
                "pwa_waiting": 1,
                "needs_you": 2,
                "sent_back_equal": True,
                "my_requests_equal": True,
                "ok": True,
                "differences": [],
                "skipped": [],
            },
        )

    def test_an_empty_inbox_and_empty_lists_are_ok(self):
        self.pending = {"groups": [], "total": 0}
        self.pwa_inbox = inbox_of(self.pending)
        self.pwa_count = count_of(self.pending)
        self.sent_back_rows, self.pwa_sent_back = [], []
        self.tables.rows[PM_ACTION] = []
        self.pwa_requests = []

        report = self.report()

        self.assertTrue(report["ok"])
        self.assertEqual((report["desk_total"], report["pwa_total"], report["needs_you"]), (0, 0, 0))

    def test_it_is_a_developer_check_not_an_endpoint(self):
        self.assertNotIn(approvals_parity.parity_report, frappe.whitelisted)


class TestInbox(ParityCase):
    def test_a_pwa_total_one_lower_is_not_ok_and_names_the_total(self):
        # the PWA is consistent with itself: total 2, one of them waiting
        self.pwa_inbox["total"] = 2
        self.pwa_inbox["needs_you"] = 1

        report = self.report()

        self.assertFalse(report["ok"])
        self.assertEqual((report["desk_total"], report["pwa_total"]), (3, 2))
        self.assertEqual(report["needs_you"], 1)  # the PWA's own: 2 less 1 waiting
        self.assertIn({"field": "total", "desk": 3, "pwa": 2}, report["differences"])
        # what PM and the PWA agree on is not reported
        self.assertTrue(report["sent_back_equal"])
        self.assertTrue(report["my_requests_equal"])
        self.assertNotIn("waiting", self.fields(report))

    def test_a_waiting_count_that_differs_is_named(self):
        self.pwa_inbox["waiting"] = 0

        report = self.report()

        self.assertFalse(report["ok"])
        self.assertEqual((report["desk_waiting"], report["pwa_waiting"]), (1, 0))
        self.assertIn({"field": "waiting", "desk": 1, "pwa": 0}, report["differences"])

    def test_needs_you_is_the_pwa_total_less_its_waiting(self):
        self.pending = pm_pending(
            pm_item("WA-1"), pm_item("WA-2"), pm_item("WA-3"), pm_waiting("WA-4"), pm_waiting("WA-5")
        )
        self.pwa_inbox = inbox_of(self.pending)
        self.pwa_count = count_of(self.pending)

        report = self.report()

        self.assertTrue(report["ok"])
        self.assertEqual((report["pwa_total"], report["pwa_waiting"], report["needs_you"]), (5, 2, 3))

    def test_a_needs_you_figure_that_is_not_the_desks_total_less_waiting_is_named(self):
        self.pwa_inbox["needs_you"] = 3

        report = self.report()

        self.assertFalse(report["ok"])
        self.assertEqual(report["needs_you"], 2)  # always the PWA's total less its waiting
        self.assertEqual(report["differences"], [{"field": "needs_you", "desk": 2, "pwa": 3}])

    def test_an_item_the_list_lacks_is_named_though_the_totals_agree(self):
        self.pwa_inbox["sections"][0]["items"] = []

        report = self.report()

        self.assertFalse(report["ok"])
        self.assertEqual(
            report["differences"], [{"field": "sections", "only_desk": ["WA-1"], "only_pwa": []}]
        )

    def test_an_item_only_the_pwa_lists_is_named(self):
        self.pwa_inbox["waiting_items"].append({"action_id": "WA-99"})

        report = self.report()

        self.assertFalse(report["ok"])
        self.assertEqual(
            report["differences"], [{"field": "waiting_items", "only_desk": [], "only_pwa": ["WA-99"]}]
        )

    def test_the_order_of_the_items_is_not_compared(self):
        self.pwa_inbox["sections"].reverse()

        self.assertTrue(self.report()["ok"])

    def test_a_badge_count_that_differs_from_the_desk_is_named(self):
        self.pwa_count["total"] = 2

        report = self.report()

        self.assertFalse(report["ok"])
        self.assertEqual(report["differences"], [{"field": "count.total", "desk": 3, "pwa": 2}])
        self.assertEqual(report["pwa_total"], 3)  # the report's own figures are the inbox's

    def test_a_badge_waiting_and_needs_you_are_checked_too(self):
        self.pwa_count["waiting"] = 0
        self.pwa_count["needs_you"] = 3

        report = self.report()

        self.assertEqual(sorted(self.fields(report)), ["count.needs_you", "count.waiting"])

    def test_a_missing_figure_is_a_difference_not_a_zero(self):
        del self.pwa_inbox["waiting"]

        report = self.report()

        self.assertFalse(report["ok"])
        self.assertIn("waiting", self.fields(report))


SENT_BACK_SKIPPED = "sent_back: PM refuses this user (PermissionError)"


class TestSentBackRefusedByPm(ParityCase):
    """PM's own sent-back list raises PermissionError for a user who may not
    read one of the sent-back document types (seen for every non-admin on
    sft-uat). That comparison is then skipped, said so, and left out of `ok`."""

    def setUp(self):
        super().setUp()

        def refused():
            frappe.throw("No permission for Purchase Invoice", frappe.PermissionError)

        self.pm.get_sent_back_documents.side_effect = refused
        self.pwa_sent_back = []

    def test_the_rest_matching_is_ok_with_sent_back_skipped(self):
        report = self.report()

        self.assertTrue(report["ok"])
        self.assertIsNone(report["sent_back_equal"])
        self.assertEqual(report["skipped"], [SENT_BACK_SKIPPED])
        self.assertEqual(report["differences"], [])
        self.assertTrue(report["my_requests_equal"])
        self.assertEqual(frappe.local.message_log, [])  # PM's refusal leaves no toast

    def test_a_real_difference_elsewhere_still_is_not_ok(self):
        self.pwa_inbox = {**self.pwa_inbox, "total": self.pwa_inbox["total"] - 1}

        report = self.report()

        self.assertFalse(report["ok"])
        self.assertIn("total", self.fields(report))
        self.assertIsNone(report["sent_back_equal"])
        self.assertEqual(report["skipped"], [SENT_BACK_SKIPPED])

    def test_the_session_is_handed_back(self):
        self.report()

        self.assertEqual(frappe.session.user, RUNNER)

    def test_any_other_error_is_not_swallowed(self):
        self.pm.get_sent_back_documents.side_effect = frappe.ValidationError("broken")

        with self.assertRaises(frappe.ValidationError):
            self.report()


class TestSentBack(ParityCase):
    def test_a_document_the_pwa_does_not_list_is_named(self):
        self.pwa_sent_back = self.pwa_sent_back[:1]

        report = self.report()

        self.assertFalse(report["sent_back_equal"])
        self.assertTrue(report["my_requests_equal"])
        self.assertFalse(report["ok"])
        self.assertEqual(
            report["differences"],
            [{"field": "sent_back", "only_desk": [["Purchase Invoice", "PINV-4"]], "only_pwa": []}],
        )

    def test_a_document_only_the_pwa_lists_is_named(self):
        self.pwa_sent_back.append(sent_back_row("SINV-77"))

        report = self.report()

        self.assertFalse(report["sent_back_equal"])
        self.assertEqual(
            report["differences"],
            [{"field": "sent_back", "only_desk": [], "only_pwa": [["Sales Invoice", "SINV-77"]]}],
        )

    def test_the_same_name_in_another_document_type_is_another_document(self):
        self.pwa_sent_back[0]["doctype"] = "Delivery Note"

        report = self.report()

        self.assertFalse(report["sent_back_equal"])
        (difference,) = report["differences"]
        self.assertEqual(difference["only_desk"], [["Sales Invoice", "SINV-9"]])
        self.assertEqual(difference["only_pwa"], [["Delivery Note", "SINV-9"]])

    def test_order_and_the_other_columns_do_not_matter(self):
        self.pwa_sent_back = [
            {**row, "reason": "Different text", "sent_back_on": "2026-11-16T04:00:45Z"}
            for row in reversed(self.pwa_sent_back)
        ]

        report = self.report()

        self.assertTrue(report["sent_back_equal"])
        self.assertTrue(report["ok"])

    def test_pm_is_asked_for_the_users_own_list_as_the_pwa_asks_for_it(self):
        self.report()

        (_args, kwargs) = self.pm.get_sent_back_documents.call_args
        self.assertFalse(kwargs.get("all_users"))
        self.assertNotIn("limit", kwargs)


class TestMyRequests(ParityCase):
    def test_a_request_the_pwa_lacks_is_named(self):
        self.pwa_requests = self.pwa_requests[:1]

        report = self.report()

        self.assertFalse(report["my_requests_equal"])
        self.assertTrue(report["sent_back_equal"])
        self.assertFalse(report["ok"])
        self.assertEqual(
            report["differences"],
            [{"field": "my_requests", "only_desk": [["Purchase Invoice", "PINV-1"]], "only_pwa": []}],
        )

    def test_a_request_that_is_not_one_is_named_when_the_pwa_lists_it(self):
        not_requests = {
            "decided already (Completed)": ("Sales Invoice", "SINV-2"),
            "reassigned away (Reassigned)": ("Sales Invoice", "SINV-6"),
            "somebody else's": ("Sales Invoice", "SINV-3"),
            "Stock Entry": ("Stock Entry", "STE-1"),
            "a type PM hides": ("Gate Pass", "GP-1"),
            "cancelled": ("Sales Invoice", "SINV-4"),
            "deleted": ("Sales Invoice", "SINV-5"),
        }
        for label, (doctype, name) in not_requests.items():
            with self.subTest(label):
                self.pwa_requests = [request_item(n, d) for d, n in MY_REQUESTS]
                self.pwa_requests.append(request_item(name, doctype))

                report = self.report()

                self.assertFalse(report["my_requests_equal"])
                self.assertEqual(
                    report["differences"],
                    [{"field": "my_requests", "only_desk": [], "only_pwa": [[doctype, name]]}],
                )

    def test_one_document_with_two_open_actions_is_one_request(self):
        # SINV-1 has an Open and a Forwarded action; listing it twice is wrong
        self.pwa_requests.append(request_item("SINV-1"))

        report = self.report()

        self.assertFalse(report["my_requests_equal"])
        self.assertEqual(
            report["differences"],
            [{"field": "my_requests", "only_desk": [], "only_pwa": [["Sales Invoice", "SINV-1"]]}],
        )

    def test_the_order_does_not_matter(self):
        self.pwa_requests.reverse()

        self.assertTrue(self.report()["my_requests_equal"])

    def test_the_read_is_of_the_users_open_and_forwarded_actions(self):
        self.report()

        (read,) = self.tables.of(PM_ACTION)
        self.assertEqual(read["filters"], {"for_submitter": ME, "status": ["in", ["Open", "Forwarded"]]})

    def test_the_documents_are_looked_up_once_per_type_for_the_ones_still_alive(self):
        self.report()

        (read,) = self.tables.of("Sales Invoice")
        self.assertEqual(read["filters"]["docstatus"], ["!=", 2])
        self.assertEqual(sorted(read["filters"]["name"][1]), ["SINV-1", "SINV-4", "SINV-5"])
        self.assertEqual(len(self.tables.of("Purchase Invoice")), 1)
        # a type the approvals never handle is not read at all
        self.assertEqual(self.tables.of("Stock Entry"), [])
        self.assertEqual(self.tables.of("Gate Pass"), [])


class TestWhoItRunsAs(ParityCase):
    def test_every_source_is_read_as_the_user_and_the_session_is_handed_back(self):
        report = self.report()

        self.assertTrue(report["ok"])
        self.assertEqual(
            self.ran_as,
            {
                name: ME
                for name in (
                    "pm pending", "inbox", "count", "pm sent back", "sent_back", "my_requests", "get_all"
                )
            },
        )  # fmt: skip
        self.assertEqual(self.set_user.call_args_list, [call(ME), call(RUNNER)])
        self.assertEqual(frappe.session.user, RUNNER)

    def test_it_writes_nothing(self):
        self.report()

        names = {name for name, _args, _kwargs in frappe.local.db.method_calls}
        self.assertLessEqual(names, {"exists"})
        # PM is only ever asked its three reads
        self.assertLessEqual(
            {name for name, _args, _kwargs in self.pm.method_calls},
            {"get_my_pending_approvals", "get_sent_back_documents", "hidden_doctypes"},
        )

    def test_the_user_is_restored_whichever_comparison_raises(self):
        failing = {
            "pm pending": self.pm.get_my_pending_approvals,
            "inbox": self.inbox,
            "count": self.count,
            "pm sent back": self.pm.get_sent_back_documents,
            "sent_back": self.sent_back,
            "my_requests": self.my_requests,
            "the read of the requests": self.get_all,
        }
        for label, source in failing.items():
            with self.subTest(label):
                self.set_user.reset_mock()
                original = source.side_effect
                source.side_effect = RuntimeError(f"boom in {label}")
                try:
                    with self.assertRaisesRegex(RuntimeError, f"boom in {label}"):
                        self.report()
                finally:
                    source.side_effect = original

                self.assertEqual(frappe.session.user, RUNNER)
                self.assertEqual(self.set_user.call_args_list, [call(ME), call(RUNNER)])

    def test_the_user_is_restored_when_setting_it_fails_part_way(self):
        def broken(user):
            frappe.local.session.user = user
            if user == ME:
                raise RuntimeError("cache reset failed")

        self.set_user.side_effect = broken

        with self.assertRaisesRegex(RuntimeError, "cache reset failed"):
            self.report()

        self.assertEqual(frappe.session.user, RUNNER)


class TestRefusals(ParityCase):
    def test_a_user_that_does_not_exist_is_refused_before_anything_runs(self):
        frappe.local.db.exists.return_value = None

        with self.assertRaises(frappe.ValidationError):
            self.report("ghost@example.com")

        frappe.local.db.exists.assert_called_once_with("User", "ghost@example.com")
        self.set_user.assert_not_called()
        self.assertEqual(self.pm.method_calls, [])
        self.assertEqual(frappe.session.user, RUNNER)

    def test_a_blank_user_is_refused(self):
        for blank in ("", "  ", None):
            with self.subTest(repr(blank)):
                with self.assertRaises(frappe.ValidationError):
                    self.report(blank)
        self.set_user.assert_not_called()

    def test_a_site_without_permission_manager_is_refused_not_reported_as_ok(self):
        self._patch("vansale.steelforce.approvals.is_available", return_value=False)

        with self.assertRaises(frappe.ValidationError):
            self.report()

        self.set_user.assert_not_called()
        self.assertEqual(self.pm.method_calls, [])
        self.inbox.assert_not_called()

    def test_the_user_is_trimmed(self):
        report = self.report(f"  {ME} ")

        self.assertEqual(report["user"], ME)
        self.assertEqual(self.set_user.call_args_list, [call(ME), call(RUNNER)])


# ─── the report against the real endpoints ────────────────────────────────────


class RealEndpointsCase(SiteFreeCase):
    """`inbox`, `count`, `sent_back` and `my_requests` are the real ones; PM and
    the tables are stubs. sara has an Approval Pending item, a Decision Pending
    one and one forwarded away, a sent-back invoice, and two requests."""

    def setUp(self):
        super().setUp()
        frappe.local.session.user = RUNNER
        frappe.local.db.exists.return_value = ME
        self._patch("vansale.steelforce.approvals.is_available", return_value=True)
        self.pm = MagicMock(name="pm")
        self.pm.hidden_doctypes.return_value = ["Gate Pass"]
        self._patch("vansale.steelforce.approvals._pm", return_value=self.pm)
        self._patch("vansale.steelforce.approvals._party_amounts", return_value={})
        self._patch("vansale.steelforce.approvals._action_flags", return_value={})
        self._patch("vansale.steelforce.approvals_extra.nowdate", return_value="2026-11-19")
        self._patch(
            "frappe.set_user", side_effect=lambda user: setattr(frappe.local.session, "user", user)
        )

        self.pm.get_my_pending_approvals.return_value = pm_pending(
            pm_item("WA-1"),
            pm_item("WA-2", doctype="Purchase Invoice", docname="PINV-7", category="Decision Pending"),
            pm_waiting("WA-3"),
        )
        self.pm.get_sent_back_documents.return_value = [sent_back_row("SINV-9")]

        self.tables = Tables()
        self.tables.rows = my_world()
        self.tables.rows[PM_ROLE] = []
        self.tables.rows["User"] = [{"name": OTHER, "full_name": "Omar Saleh"}]
        # PINV-1 was forwarded: the Forwarded action and the ad-hoc one for Omar
        self.tables.rows[PM_ACTION].append(
            action_row(
                "WA-20", "Purchase Invoice", "PINV-1", is_adhoc=1, assigned_to=OTHER,
                creation=datetime(2026, 11, 12, 9, 30),
            )
        )  # fmt: skip
        self._patch("frappe.get_all", side_effect=self.tables)


class TestAgainstTheRealEndpoints(RealEndpointsCase):
    def test_the_real_endpoints_agree_with_pm_and_the_independent_read(self):
        report = approvals_parity.parity_report(ME)

        self.assertEqual(report["differences"], [])
        self.assertTrue(report["ok"])
        self.assertEqual(
            {key: report[key] for key in KEYS - {"differences"}},
            {
                "user": ME,
                "desk_total": 3,
                "pwa_total": 3,
                "desk_waiting": 1,
                "pwa_waiting": 1,
                "needs_you": 2,
                "sent_back_equal": True,
                "my_requests_equal": True,
                "ok": True,
                "skipped": [],
            },
        )
        self.assertEqual(frappe.session.user, RUNNER)

    def test_the_report_has_the_documented_keys_and_nothing_else(self):
        self.assertEqual(set(approvals_parity.parity_report(ME)), KEYS)

    def test_pm_refusing_its_own_sent_back_list_skips_that_comparison(self):
        self.pm.get_sent_back_documents.side_effect = frappe.PermissionError
        self._patch("frappe.log_error")

        report = approvals_parity.parity_report(ME)

        self.assertTrue(report["ok"])
        self.assertIsNone(report["sent_back_equal"])
        self.assertEqual(report["skipped"], ["sent_back: PM refuses this user (PermissionError)"])

    def test_the_total_is_pms_own_not_a_count_of_the_items(self):
        # PM claims 4 but lists 3 items: the desk shows PM's 4 and so does the PWA
        self.pm.get_my_pending_approvals.return_value["total"] = 4

        report = approvals_parity.parity_report(ME)

        self.assertEqual((report["desk_total"], report["pwa_total"]), (4, 4))
        self.assertEqual(report["needs_you"], 3)
        self.assertTrue(report["ok"])

    def test_a_sent_back_row_the_pwa_leaves_out_is_reported(self):
        # PM does not return a Stock Entry here; if it ever did, the PWA drops it
        self.pm.get_sent_back_documents.return_value = [
            sent_back_row("SINV-9"),
            sent_back_row("STE-1", "Stock Entry"),
        ]

        report = approvals_parity.parity_report(ME)

        self.assertFalse(report["ok"])
        self.assertFalse(report["sent_back_equal"])
        self.assertEqual(
            report["differences"],
            [{"field": "sent_back", "only_desk": [["Stock Entry", "STE-1"]], "only_pwa": []}],
        )

    def test_a_new_open_request_on_a_draft_is_in_both_lists(self):
        self.tables.rows[PM_ACTION].append(action_row("WA-30", "Sales Invoice", "SINV-1B"))
        self.tables.rows["Sales Invoice"].append({"name": "SINV-1B", "docstatus": 0})

        report = approvals_parity.parity_report(ME)

        self.assertTrue(report["my_requests_equal"])
        self.assertTrue(report["ok"])

    def test_nothing_is_written(self):
        approvals_parity.parity_report(ME)

        names = {name for name, _args, _kwargs in frappe.local.db.method_calls}
        self.assertEqual(names - {"exists"}, set())


if __name__ == "__main__":
    unittest.main()
