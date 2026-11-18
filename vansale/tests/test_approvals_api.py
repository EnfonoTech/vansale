"""Approvals endpoints (`vansale.steelforce.approvals`) without a site and
without `permission_manager` (PM): every PM call goes through `approvals._pm()`,
which these tests replace, and every database read is a stub that answers from
a table the test writes down (an unexpected read fails the test).

Run: cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale \
     ../env/bin/python -m unittest vansale.tests.test_approvals_api -v
"""

from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch, sentinel

import frappe
import pymysql
from frappe.query_builder import get_query_builder
from frappe.query_builder.utils import patch_query_execute

from vansale.steelforce import approvals
from vansale.steelforce.approvals_rules import inbox_stats
from vansale.tests import _site_free


_MISSING = object()


def pm_item(name: str, **overrides) -> dict:
    """One item as PM's `get_my_pending_approvals()` returns it."""
    item = {
        "name": name,
        "doctype": "Sales Invoice",
        "transaction": "Sales Invoice",
        "transaction_filter": "Sales Invoice",
        "docname": f"DOC-{name}",
        "date": "10/11/26 09:30",
        "creation_iso": "2026-11-10T09:30:00",
        "priority": "Medium",
        "state": "Pending Approval",
        "role_id": "Finance Head",
        "holder": "",
        "days": 2,
        "creator": "Ali Hassan",
        "category": "Approval Pending",
        "available_actions": ["Approve", "Reject"],
        "doc_url": f"/app/sales-invoice/DOC-{name}",
        "is_adhoc": False,
        "adhoc_for": "",
        "return_to_originator": False,
        "is_waiting": False,
        "waiting_with": "",
    }
    item.update(overrides)
    return item


def pm_waiting(name: str, **overrides) -> dict:
    """An item forwarded away: no buttons, someone else holds it."""
    return pm_item(
        name,
        is_waiting=True,
        waiting_with="Fatima Noor",
        holder="Fatima Noor",
        available_actions=[],
        **overrides,
    )


def pm_pending(*items: dict, total: int | None = None) -> dict:
    """PM's answer: the items grouped by category in first-seen order."""
    groups: dict[str, list] = {}
    for item in items:
        groups.setdefault(item["category"], []).append(item)
    return {
        "total": len(items) if total is None else total,
        "groups": [{"label": label, "items": rows} for label, rows in groups.items()],
    }


def fake_reader(function: str, rows_by_doctype: dict[str, list[dict]]):
    """A stand-in for `frappe.get_all` / `frappe.get_list` (`function` names it
    in the failure message) that answers from `rows_by_doctype` and fails on any
    other doctype. `.calls` lists `(doctype, kwargs)` for every call."""
    calls: list = []

    def read(doctype, *args, **kwargs):
        calls.append((doctype, kwargs))
        if doctype not in rows_by_doctype:
            raise AssertionError(f"unexpected {function}({doctype!r}, {kwargs})")
        return [frappe._dict(row) for row in rows_by_doctype[doctype]]

    read.calls = calls
    return read


def meta_with(*fieldnames: str):
    """A stand-in for `frappe.get_meta(doctype)` that has these fields."""
    return types.SimpleNamespace(has_field=lambda fieldname: fieldname in fieldnames)


class SiteFreeCase(unittest.TestCase):
    def setUp(self):
        _site_free.setup_site_free()
        self.addCleanup(_site_free.teardown_site_free)

    def _patch(self, target: str, *args, **kwargs):
        patcher = patch(target, *args, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _use_get_all(self, rows_by_doctype: dict[str, list[dict]]):
        get_all = fake_reader("get_all", rows_by_doctype)
        self._patch("frappe.get_all", get_all)
        return get_all

    def _use_get_list(self, rows_by_doctype: dict[str, list[dict]]):
        get_list = fake_reader("get_list", rows_by_doctype)
        self._patch("frappe.get_list", get_list)
        return get_list


class ApiCase(SiteFreeCase):
    """PM is installed (stubbed as `self.pm`); the three enrichment reads are
    stubbed to "nothing known" and any other `get_all` fails the test."""

    def setUp(self):
        super().setUp()
        self.available = self._patch("vansale.steelforce.approvals.is_available", return_value=True)
        self.pm = MagicMock(name="pm")
        self._patch("vansale.steelforce.approvals._pm", return_value=self.pm)
        self.party_amounts = self._patch("vansale.steelforce.approvals._party_amounts", return_value={})
        self.action_flags = self._patch("vansale.steelforce.approvals._action_flags", return_value={})
        self.get_all = self._use_get_all({})


# ─── availability ─────────────────────────────────────────────────────────────


class TestAvailability(SiteFreeCase):
    def test_available_when_pm_is_installed_and_its_table_exists(self):
        self._patch("frappe.get_installed_apps", return_value=["frappe", "permission_manager"])
        frappe.local.db.table_exists.return_value = True

        self.assertTrue(approvals.is_available())
        frappe.local.db.table_exists.assert_called_once_with("PM Workflow Action")

    def test_not_available_without_the_pm_app(self):
        self._patch("frappe.get_installed_apps", return_value=["frappe", "erpnext"])

        self.assertFalse(approvals.is_available())
        frappe.local.db.table_exists.assert_not_called()

    def test_not_available_while_the_action_table_is_missing(self):
        self._patch("frappe.get_installed_apps", return_value=["frappe", "permission_manager"])
        frappe.local.db.table_exists.return_value = False

        self.assertFalse(approvals.is_available())

    def test_availability_endpoint_says_whether_it_is_enabled(self):
        with patch.object(approvals, "is_available", return_value=True):
            self.assertEqual(approvals.availability(), {"enabled": True})
        with patch.object(approvals, "is_available", return_value=False):
            self.assertEqual(approvals.availability(), {"enabled": False})


class TestEndpointsAreWhitelistedGet(unittest.TestCase):
    def test_availability_inbox_and_count_answer_get_only(self):
        for function in (approvals.availability, approvals.inbox, approvals.count, approvals.detail):
            with self.subTest(function=function.__name__):
                self.assertIn(function, frappe.whitelisted)
                self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[function], ["GET"])
                self.assertNotIn(function, frappe.guest_methods)

    def test_apply_and_apply_bulk_answer_post_only(self):
        for function in (approvals.apply, approvals.apply_bulk):
            with self.subTest(function=function.__name__):
                self.assertIn(function, frappe.whitelisted)
                self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[function], ["POST"])
                self.assertNotIn(function, frappe.guest_methods)


# ─── the PM wiring ────────────────────────────────────────────────────────────


def _module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


EXPECTED_PM_NAMES = {
    "get_my_pending_approvals": sentinel.pending,
    "get_transitions": sentinel.transitions,
    "apply_workflow": sentinel.apply,
    "has_approval_access": sentinel.access,
    "get_open_return_adhoc_action": sentinel.open_return,
    "get_document_lifecycle": sentinel.lifecycle,
    "forward_workflow_action": sentinel.forward,
    "return_adhoc_to_originator": sentinel.return_adhoc,
    "get_sent_back_documents": sentinel.sent_back,
    "get_my_approval_history": sentinel.history,
    "can_act_on": sentinel.can_act,
    "get_workflow": sentinel.workflow,
    "hidden_doctypes": sentinel.hidden,
    "transaction_label": sentinel.label,
}


def _pm_modules(drop: str = "") -> dict:
    """PM's three modules as `sys.modules` entries, `drop` left out of them."""

    def module(name, **attrs):
        return _module(name, **{key: value for key, value in attrs.items() if key != drop})

    pm_approvals = module(
        "approvals",
        get_my_pending_approvals=sentinel.pending,
        get_document_lifecycle=sentinel.lifecycle,
        get_sent_back_documents=sentinel.sent_back,
        get_my_approval_history=sentinel.history,
        transaction_label=sentinel.label,
        _hidden_doctypes=sentinel.hidden,
    )
    pm_workflow = module(
        "workflow",
        get_workflow=sentinel.workflow,
        get_transitions=sentinel.transitions,
        apply_workflow=sentinel.apply,
        has_approval_access=sentinel.access,
        get_open_return_adhoc_action=sentinel.open_return,
    )
    pm_actions = module(
        "pm_workflow_action",
        forward_workflow_action=sentinel.forward,
        return_adhoc_to_originator=sentinel.return_adhoc,
        _can_act_on=sentinel.can_act,
    )
    return {
        "permission_manager.permission_manager.api": _module("api", approvals=pm_approvals),
        "permission_manager.permission_manager": _module("pm", workflow=pm_workflow),
        "permission_manager.permission_manager.doctype.pm_workflow_action": _module(
            "action", pm_workflow_action=pm_actions
        ),
    }


class TestPmNamespace(unittest.TestCase):
    def test_pm_maps_every_callable(self):
        with patch.dict(sys.modules, _pm_modules()):
            pm = approvals._pm()
            mapped = {name: getattr(pm, name) for name in EXPECTED_PM_NAMES}

        self.assertEqual(mapped, EXPECTED_PM_NAMES)
        self.assertEqual(set(approvals.PM_FUNCTIONS), set(EXPECTED_PM_NAMES))

    def test_pm_imports_nothing_until_a_function_is_used(self):
        # PM is not installed here: making the namespace must not fail
        pm = approvals._pm()

        with self.assertRaises(ImportError):
            pm.get_my_pending_approvals

    def test_a_pm_without_one_private_name_breaks_only_what_needs_it(self):
        with patch.dict(sys.modules, _pm_modules(drop="_can_act_on")):
            pm = approvals._pm()

            with self.assertRaises(AttributeError):
                pm.can_act_on
            self.assertIs(pm.get_my_pending_approvals, sentinel.pending)
            self.assertIs(pm.hidden_doctypes, sentinel.hidden)
            self.assertIs(pm.forward_workflow_action, sentinel.forward)

    def test_a_name_pm_is_not_asked_for_is_an_attribute_error(self):
        with self.assertRaises(AttributeError):
            approvals._pm().delete_everything


# ─── inbox and count ──────────────────────────────────────────────────────────


class TestInbox(ApiCase):
    def setUp(self):
        super().setUp()
        # Needs you: a (High, 40 days), b (Critical, 5), c (Low, 31).
        # Waiting on others: d (High, 50 days), e.
        self.a = pm_item("A", doctype="Sales Invoice", priority="High", days=40, category="Approval Pending")
        self.b = pm_item("B", doctype="Journal Entry", transaction="Journal Entry", priority="Critical", days=5,
                         category="Approval Pending")
        self.c = pm_item("C", doctype="Purchase Order", transaction="Purchase Order", priority="Low", days=31,
                         category="Decision Pending")
        self.d = pm_waiting("D", doctype="Sales Order", transaction="Sales Order", priority="High", days=50,
                            category="Approval Pending")
        self.e = pm_waiting("E", doctype="Quotation", transaction="Quotation", priority="Medium", days=1,
                            category="Decision Pending")
        self.pm.get_my_pending_approvals.return_value = pm_pending(self.a, self.b, self.c, self.d, self.e)

    def test_totals_split_between_needs_you_and_waiting(self):
        result = approvals.inbox()

        self.assertEqual(result["total"], 5)
        self.assertEqual(result["waiting"], 2)
        self.assertEqual(result["needs_you"], 3)
        self.assertEqual([i["action_id"] for i in result["waiting_items"]], ["D", "E"])
        self.assertTrue(all(i["is_waiting"] for i in result["waiting_items"]))

    def test_needs_you_items_are_grouped_by_category_in_pm_order(self):
        result = approvals.inbox()

        self.assertEqual(
            [(s["category"], [i["action_id"] for i in s["items"]]) for s in result["sections"]],
            [("Approval Pending", ["A", "B"]), ("Decision Pending", ["C"])],
        )

    def test_a_category_holding_only_waiting_items_makes_no_section(self):
        self.pm.get_my_pending_approvals.return_value = pm_pending(self.a, self.e)

        result = approvals.inbox()

        self.assertEqual([s["category"] for s in result["sections"]], ["Approval Pending"])
        self.assertEqual([i["action_id"] for i in result["waiting_items"]], ["E"])

    def test_stats_count_only_the_items_waiting_on_the_user(self):
        result = approvals.inbox()

        # d is High and 50 days old but waits on someone else.
        self.assertEqual(result["stats"], {"high": 2, "overdue": 2})
        self.assertEqual(result["stats"], inbox_stats([self.a, self.b, self.c]))

    def test_count_gives_the_same_numbers_without_building_items(self):
        result = approvals.count()

        self.assertEqual(result, {"total": 5, "needs_you": 3, "waiting": 2, "high": 2, "overdue": 2})
        self.party_amounts.assert_not_called()
        self.action_flags.assert_not_called()
        self.assertEqual(self.get_all.calls, [])

    def test_total_is_pms_own_total(self):
        self.pm.get_my_pending_approvals.return_value = pm_pending(self.a, self.d, total=9)

        self.assertEqual(approvals.count()["total"], 9)
        self.assertEqual(approvals.count()["needs_you"], 8)
        self.assertEqual(approvals.inbox()["total"], 9)

    def test_an_empty_pm_answer_is_an_empty_inbox(self):
        self.pm.get_my_pending_approvals.return_value = {"groups": [], "total": 0}

        result = approvals.inbox()

        self.assertEqual(
            {k: v for k, v in result.items() if k != "fetched_at"},
            {
                "total": 0,
                "needs_you": 0,
                "waiting": 0,
                "stats": {"high": 0, "overdue": 0},
                "sections": [],
                "waiting_items": [],
            },
        )
        self.assertEqual(
            approvals.count(), {"total": 0, "needs_you": 0, "waiting": 0, "high": 0, "overdue": 0}
        )

    def test_fetched_at_is_a_utc_iso_stamp(self):
        stamp = approvals.inbox()["fetched_at"]

        self.assertIsInstance(stamp, str)
        self.assertTrue(stamp.endswith("Z"), stamp)

    def test_an_item_carries_the_contract_fields(self):
        item = pm_item(
            "W-1",
            doctype="Sales Invoice",
            transaction="Sales Return",
            docname="SINV-0001",
            priority="High",
            days=3,
            state="Pending Finance",
            role_id="Finance Head",
            creator="Ali Hassan",
            category="Approval Pending",
            is_adhoc=False,
            return_to_originator=False,
        )
        self.pm.get_my_pending_approvals.return_value = pm_pending(item)
        self.party_amounts.return_value = {
            ("Sales Invoice", "SINV-0001"): {"party": "Acme Trading", "amount": 1250.5, "currency": "BHD"}
        }

        result = approvals.inbox()

        self.assertEqual(
            result["sections"][0]["items"][0],
            {
                "action_id": "W-1",
                "doctype": "Sales Invoice",
                "docname": "SINV-0001",
                "transaction": "Sales Return",
                "area": "Sales",
                "party": "Acme Trading",
                "amount": 1250.5,
                "currency": "BHD",
                "priority": "High",
                "state": "Pending Finance",
                "role_id": "Finance Head",
                "days": 3,
                "creator": "Ali Hassan",
                "category": "Approval Pending",
                "is_adhoc": False,
                "forwarded_by": "",
                "return_to_originator": False,
                "is_waiting": False,
                "waiting_with": "",
                "available_actions": [
                    {
                        "action": "Approve",
                        "require_comment": False,
                        "require_attachment": False,
                        "is_return_for_correction": False,
                    },
                    {
                        "action": "Reject",
                        "require_comment": False,
                        "require_attachment": False,
                        "is_return_for_correction": False,
                    },
                ],
            },
        )

    def test_a_document_nothing_is_known_about_still_shows(self):
        # The enrichment found no row (deleted, or the doctype has no such
        # fields): no party, no amount, no currency, and the area is "Other".
        self.pm.get_my_pending_approvals.return_value = pm_pending(
            pm_item("X", doctype="Gate Pass", transaction="Gate Pass", docname="GP-1")
        )

        item = approvals.inbox()["sections"][0]["items"][0]

        self.assertEqual((item["party"], item["amount"], item["currency"]), ("", None, ""))
        self.assertEqual(item["area"], "Other")

    def test_available_actions_are_pms_names_with_the_transition_flags(self):
        self.pm.get_my_pending_approvals.return_value = pm_pending(
            pm_item("A", available_actions=["Approve", "Reject", "Escalate"]), self.d
        )
        self.action_flags.return_value = {
            ("Sales Invoice", "Pending Approval"): {
                "Approve": {"require_comment": False, "require_attachment": True, "is_return_for_correction": False},
                "Reject": {"require_comment": True, "require_attachment": False, "is_return_for_correction": True},
            }
        }

        result = approvals.inbox()

        actions = result["sections"][0]["items"][0]["available_actions"]
        self.assertEqual(
            actions,
            [
                {"action": "Approve", "require_comment": False, "require_attachment": True,
                 "is_return_for_correction": False},
                {"action": "Reject", "require_comment": True, "require_attachment": False,
                 "is_return_for_correction": True},
                # no transition row found for this name: nothing is required
                {"action": "Escalate", "require_comment": False, "require_attachment": False,
                 "is_return_for_correction": False},
            ],
        )
        self.assertEqual(result["waiting_items"][0]["available_actions"], [])

    def test_the_enrichment_reads_the_items_once(self):
        self.action_flags.return_value = {}

        approvals.inbox()

        (party_items,) = self.party_amounts.call_args.args
        self.assertEqual(sorted(i["name"] for i in party_items), ["A", "B", "C", "D", "E"])
        (flag_items,) = self.action_flags.call_args.args
        self.assertEqual(sorted(i["name"] for i in flag_items), ["A", "B", "C", "D", "E"])
        self.assertEqual(self.party_amounts.call_count, 1)
        self.assertEqual(self.action_flags.call_count, 1)

    def test_an_ad_hoc_item_names_the_user_who_forwarded_it(self):
        forwarded = pm_item(
            "WA-2", is_adhoc=True, adhoc_for="WA-1", return_to_originator=True, category="Decision Pending"
        )
        self.pm.get_my_pending_approvals.return_value = pm_pending(self.a, forwarded)
        self._use_get_all(
            {
                "PM Workflow Action": [{"name": "WA-1", "completed_by": "ali@example.com"}],
                "User": [{"name": "ali@example.com", "full_name": "Ali Hassan"}],
            }
        )

        result = approvals.inbox()

        by_id = {i["action_id"]: i for s in result["sections"] for i in s["items"]}
        self.assertEqual(by_id["WA-2"]["forwarded_by"], "Ali Hassan")
        self.assertTrue(by_id["WA-2"]["is_adhoc"])
        self.assertTrue(by_id["WA-2"]["return_to_originator"])
        self.assertEqual(by_id["A"]["forwarded_by"], "")


class TestNothingWithoutPm(ApiCase):
    def setUp(self):
        super().setUp()
        self.available.return_value = False

    def test_every_endpoint_answers_empty_and_asks_nobody(self):
        self.assertEqual(approvals.availability(), {"enabled": False})
        self.assertEqual(
            approvals.count(), {"total": 0, "needs_you": 0, "waiting": 0, "high": 0, "overdue": 0}
        )
        inbox = approvals.inbox()
        self.assertEqual(
            {k: v for k, v in inbox.items() if k != "fetched_at"},
            {
                "total": 0,
                "needs_you": 0,
                "waiting": 0,
                "stats": {"high": 0, "overdue": 0},
                "sections": [],
                "waiting_items": [],
            },
        )
        self.assertTrue(inbox["fetched_at"].endswith("Z"))

        self.assertEqual(self.pm.mock_calls, [])
        self.assertEqual(self.get_all.calls, [])
        frappe.local.db.sql.assert_not_called()


# ─── enrichment helpers ───────────────────────────────────────────────────────


def _doc(doctype: str, docname: str) -> dict:
    return {"doctype": doctype, "docname": docname}


class TestPartyAmounts(SiteFreeCase):
    """Party and amount are read as the signed-in user: `frappe.get_list` (roles,
    User Permissions, field-level permissions), never `frappe.get_all`."""

    def setUp(self):
        super().setUp()
        self.metas = {
            "Sales Invoice": meta_with("customer", "customer_name", "grand_total", "currency", "company"),
            "Journal Entry": meta_with("title", "total_debit", "company"),
        }
        self._patch("frappe.get_meta", side_effect=lambda doctype: self._meta(doctype))
        self.currency_of = self._patch(
            "frappe.get_cached_value", side_effect=lambda doctype, name, field: {"Steel Co": "BHD"}.get(name)
        )
        self.unreadable: set[str] = set()
        self.has_permission = self._patch(
            "frappe.has_permission",
            side_effect=lambda doctype, ptype="read", **kwargs: doctype not in self.unreadable,
        )
        # `get_all` would skip the user's permissions: any call fails the test.
        self.get_all = self._use_get_all({})
        # frappe.db is a MagicMock here; give it the driver's real error classes.
        for name in ("ProgrammingError", "OperationalError", "InternalError", "DataError"):
            setattr(frappe.local.db, name, getattr(pymysql, name))

    def _meta(self, doctype):
        if doctype not in self.metas:
            raise frappe.DoesNotExistError(doctype)
        return self.metas[doctype]

    def test_one_query_per_doctype_never_per_row(self):
        get_list = self._use_get_list(
            {
                "Sales Invoice": [
                    {"name": "SINV-1", "customer_name": "Acme", "grand_total": 120.5, "currency": "USD",
                     "company": "Steel Co"},
                    {"name": "SINV-2", "customer_name": "Beta", "grand_total": 0, "currency": "",
                     "company": "Steel Co"},
                ],
                "Journal Entry": [
                    {"name": "JV-1", "title": "Rent", "total_debit": 1000, "company": "Steel Co"},
                ],
            }
        )
        items = [
            _doc("Sales Invoice", "SINV-1"),
            _doc("Sales Invoice", "SINV-2"),
            _doc("Sales Invoice", "SINV-1"),
            _doc("Journal Entry", "JV-1"),
            _doc("Sales Invoice", "SINV-9"),
        ]

        result = approvals._party_amounts(items)

        self.assertEqual([call[0] for call in get_list.calls], ["Sales Invoice", "Journal Entry"])
        invoice_call = get_list.calls[0][1]
        self.assertEqual(invoice_call["filters"], {"name": ["in", ["SINV-1", "SINV-2", "SINV-9"]]})
        self.assertEqual(
            invoice_call["fields"], ["name", "customer_name", "grand_total", "currency", "company"]
        )
        self.assertEqual(invoice_call["limit_page_length"], 0)  # every name asked for, no page of 20
        self.assertEqual(
            result,
            {
                ("Sales Invoice", "SINV-1"): {"party": "Acme", "amount": 120.5, "currency": "USD"},
                # no currency on the document: the company's own
                ("Sales Invoice", "SINV-2"): {"party": "Beta", "amount": 0.0, "currency": "BHD"},
                ("Journal Entry", "JV-1"): {"party": "Rent", "amount": 1000.0, "currency": "BHD"},
            },
        )
        # SINV-9 is not found, so it is not in the answer.
        self.assertNotIn(("Sales Invoice", "SINV-9"), result)
        self.assertEqual(self.get_all.calls, [])

    def test_a_company_is_looked_up_once_not_per_row(self):
        self._use_get_list(
            {
                "Sales Invoice": [
                    {"name": "SINV-1", "customer_name": "Acme", "grand_total": 1, "currency": "", "company": "Steel Co"},
                    {"name": "SINV-2", "customer_name": "Beta", "grand_total": 2, "currency": "", "company": "Steel Co"},
                ],
            }
        )

        approvals._party_amounts([_doc("Sales Invoice", "SINV-1"), _doc("Sales Invoice", "SINV-2")])

        self.assertEqual(self.currency_of.call_count, 1)

    def test_a_doctype_the_user_may_not_read_gives_nothing_and_no_error(self):
        self.unreadable.add("Sales Invoice")
        get_list = self._use_get_list(
            {"Journal Entry": [{"name": "JV-1", "title": "Rent", "total_debit": 5, "company": "Steel Co"}]}
        )
        log_error = self._patch("frappe.log_error")

        result = approvals._party_amounts([_doc("Sales Invoice", "SINV-1"), _doc("Journal Entry", "JV-1")])

        self.assertEqual(list(result), [("Journal Entry", "JV-1")])
        self.has_permission.assert_any_call("Sales Invoice", "read")
        self.assertEqual([call[0] for call in get_list.calls], ["Journal Entry"])  # never asked
        log_error.assert_not_called()
        self.assertEqual(frappe.local.message_log, [])

    def test_a_row_the_users_permissions_filter_out_is_left_out(self):
        # A User Permission (a branch, a company) makes `get_list` drop SINV-2
        # from the answer; PM still lists the document, so it shows with no
        # party and no amount (see TestInbox).
        get_list = self._use_get_list(
            {
                "Sales Invoice": [
                    {"name": "SINV-1", "customer_name": "Acme", "grand_total": 3, "currency": "BHD",
                     "company": "Steel Co"},
                ]
            }
        )

        result = approvals._party_amounts([_doc("Sales Invoice", "SINV-1"), _doc("Sales Invoice", "SINV-2")])

        self.assertEqual(get_list.calls[0][1]["filters"], {"name": ["in", ["SINV-1", "SINV-2"]]})
        self.assertEqual(list(result), [("Sales Invoice", "SINV-1")])

    def test_a_field_the_user_may_not_read_comes_back_with_no_value(self):
        # `get_list` leaves out a field above the user's permission level, so
        # the row has no `grand_total` key at all: no amount, not 0.
        self._use_get_list(
            {"Sales Invoice": [{"name": "SINV-1", "customer_name": "Acme", "currency": "USD", "company": "Steel Co"}]}
        )

        result = approvals._party_amounts([_doc("Sales Invoice", "SINV-1")])

        self.assertEqual(result, {("Sales Invoice", "SINV-1"): {"party": "Acme", "amount": None, "currency": "USD"}})

    def test_a_permission_error_from_the_read_is_blank_not_an_error_or_a_toast(self):
        def get_list(doctype, *args, **kwargs):
            if doctype == "Sales Invoice":
                # what `frappe.throw(..., PermissionError)` does before raising
                frappe.local.message_log.append({"message": "No permission to read Sales Invoice"})
                raise frappe.PermissionError
            return [frappe._dict(name="JV-1", title="Rent", total_debit=5, company="Steel Co")]

        self._patch("frappe.get_list", get_list)
        log_error = self._patch("frappe.log_error")

        result = approvals._party_amounts([_doc("Sales Invoice", "SINV-1"), _doc("Journal Entry", "JV-1")])

        self.assertEqual(list(result), [("Journal Entry", "JV-1")])
        self.assertEqual(frappe.local.message_log, [])  # no stray toast on the 200 response
        log_error.assert_not_called()  # and no Error Log row every minute

    def test_a_permission_error_that_left_no_message_keeps_the_earlier_ones(self):
        frappe.local.message_log.append({"message": "earlier"})

        def get_list(doctype, *args, **kwargs):
            raise frappe.PermissionError

        self._patch("frappe.get_list", get_list)

        self.assertEqual(approvals._party_amounts([_doc("Sales Invoice", "SINV-1")]), {})
        self.assertEqual(frappe.local.message_log, [{"message": "earlier"}])

    def test_a_database_error_is_deferred_to_the_error_log_and_that_doctype_skipped(self):
        error_log = MagicMock(name="Error Log")
        get_doc = self._patch("frappe.get_doc", return_value=error_log)

        def get_list(doctype, *args, **kwargs):
            if doctype == "Sales Invoice":
                raise pymysql.err.OperationalError(1054, "Unknown column 'grand_total' in 'field list'")
            return [frappe._dict(name="JV-1", title="Rent", total_debit=5, company="Steel Co")]

        self._patch("frappe.get_list", get_list)

        result = approvals._party_amounts([_doc("Sales Invoice", "SINV-1"), _doc("Journal Entry", "JV-1")])

        self.assertEqual(list(result), [("Journal Entry", "JV-1")])
        # The real `frappe.log_error` ran. This request is a GET, which ends in
        # a rollback: a row inserted now would be discarded, so it is deferred.
        error_log.deferred_insert.assert_called_once_with()
        error_log.insert.assert_not_called()
        self.assertIn("Sales Invoice", get_doc.call_args.kwargs["method"])

    def test_an_error_that_is_not_a_database_error_is_not_swallowed(self):
        def get_list(doctype, *args, **kwargs):
            raise ValueError("a bug, not a bad field")

        self._patch("frappe.get_list", get_list)
        log_error = self._patch("frappe.log_error")

        with self.assertRaises(ValueError):
            approvals._party_amounts([_doc("Sales Invoice", "SINV-1")])
        log_error.assert_not_called()

    def test_a_doctype_that_does_not_exist_is_skipped(self):
        get_list = self._use_get_list({})

        result = approvals._party_amounts([_doc("Gone Doctype", "G-1")])

        self.assertEqual(result, {})
        self.assertEqual(get_list.calls, [])

    def test_a_doctype_with_no_party_or_amount_field_is_not_queried(self):
        self.metas["Gate Pass"] = meta_with("company", "currency")
        get_list = self._use_get_list({})

        result = approvals._party_amounts([_doc("Gate Pass", "GP-1")])

        self.assertEqual(result, {})
        self.assertEqual(get_list.calls, [])

    def test_a_document_with_no_amount_field_has_a_party_and_no_amount(self):
        self.metas["Customer"] = meta_with("customer_name")
        self._use_get_list({"Customer": [{"name": "CUST-1", "customer_name": "Acme"}]})

        result = approvals._party_amounts([_doc("Customer", "CUST-1")])

        self.assertEqual(result, {("Customer", "CUST-1"): {"party": "Acme", "amount": None, "currency": ""}})

    def test_no_items_no_queries(self):
        get_list = self._use_get_list({})

        self.assertEqual(approvals._party_amounts([]), {})
        self.assertEqual(get_list.calls, [])


class TestActionFlags(SiteFreeCase):
    def setUp(self):
        super().setUp()
        # frappe.init binds the query builder and patches `.run`; with no site
        # that is done here.
        saved = getattr(frappe.local, "qb", _MISSING)
        frappe.local.qb = get_query_builder("mariadb")
        patch_query_execute()
        self.addCleanup(self._restore_qb, saved)

    @staticmethod
    def _restore_qb(saved):
        if saved is _MISSING:
            try:
                delattr(frappe.local, "qb")
            except AttributeError:
                pass
        else:
            frappe.local.qb = saved

    def test_one_query_over_the_active_workflows_gives_the_flags_by_state(self):
        frappe.local.db.sql.return_value = [
            frappe._dict(document_type="Sales Invoice", state="Pending Approval", action="Approve",
                         require_comment=0, require_attachment=0, is_return_for_correction=0),
            frappe._dict(document_type="Sales Invoice", state="Pending Approval", action="Reject",
                         require_comment=1, require_attachment=0, is_return_for_correction=1),
            # the same action for a second approver role: flags are OR-ed
            frappe._dict(document_type="Sales Invoice", state="Pending Approval", action="Approve",
                         require_comment=0, require_attachment=1, is_return_for_correction=0),
            frappe._dict(document_type="Journal Entry", state="Draft", action="Send for Approval",
                         require_comment=0, require_attachment=1, is_return_for_correction=0),
            # a doctype and a state that were each asked for, but not together
            frappe._dict(document_type="Journal Entry", state="Pending Approval", action="Approve",
                         require_comment=1, require_attachment=0, is_return_for_correction=0),
        ]
        items = [
            pm_item("A", doctype="Sales Invoice", state="Pending Approval", available_actions=["Approve", "Reject"]),
            pm_item("B", doctype="Sales Invoice", state="Pending Approval", available_actions=["Approve", "Reject"]),
            pm_item("C", doctype="Journal Entry", state="Draft", available_actions=["Send for Approval"]),
            pm_waiting("D", doctype="Sales Order", state="Pending Approval"),
        ]

        result = approvals._action_flags(items)

        self.assertEqual(frappe.local.db.sql.call_count, 1)
        query, params = frappe.local.db.sql.call_args.args[:2]
        self.assertIn("is_active", query)
        self.assertEqual(
            sorted(v for v in params.values() if isinstance(v, str)),
            ["Draft", "Journal Entry", "Pending Approval", "Sales Invoice"],
        )
        self.assertEqual(
            result,
            {
                ("Sales Invoice", "Pending Approval"): {
                    "Approve": {"require_comment": False, "require_attachment": True,
                                "is_return_for_correction": False},
                    "Reject": {"require_comment": True, "require_attachment": False,
                               "is_return_for_correction": True},
                },
                ("Journal Entry", "Draft"): {
                    "Send for Approval": {"require_comment": False, "require_attachment": True,
                                          "is_return_for_correction": False},
                },
            },
        )

    def test_items_without_actions_need_no_query(self):
        result = approvals._action_flags([pm_waiting("D"), pm_item("E", available_actions=[])])

        self.assertEqual(result, {})
        frappe.local.db.sql.assert_not_called()


class TestForwardedBy(SiteFreeCase):
    def test_names_the_user_who_completed_the_original_action(self):
        get_all = self._use_get_all(
            {
                "PM Workflow Action": [
                    {"name": "WA-1", "completed_by": "ali@example.com"},
                    {"name": "WA-5", "completed_by": "sara@example.com"},
                ],
                "User": [
                    {"name": "ali@example.com", "full_name": "Ali Hassan"},
                    {"name": "sara@example.com", "full_name": ""},
                ],
            }
        )
        items = [
            pm_item("WA-2", is_adhoc=True, adhoc_for="WA-1"),
            pm_item("WA-6", is_adhoc=True, adhoc_for="WA-5"),
            pm_item("WA-7", is_adhoc=True, adhoc_for="WA-1"),
            pm_item("WA-3"),
        ]

        result = approvals._forwarded_by(items)

        # a user with no full name shows as the user id
        self.assertEqual(result, {"WA-2": "Ali Hassan", "WA-6": "sara@example.com", "WA-7": "Ali Hassan"})
        self.assertEqual([call[0] for call in get_all.calls], ["PM Workflow Action", "User"])
        self.assertEqual(
            get_all.calls[0][1]["filters"], {"name": ["in", ["WA-1", "WA-5"]]}
        )
        self.assertEqual(
            get_all.calls[1][1]["filters"], {"name": ["in", ["ali@example.com", "sara@example.com"]]}
        )

    def test_an_original_action_nobody_completed_names_no_one(self):
        self._use_get_all({"PM Workflow Action": [{"name": "WA-1", "completed_by": None}]})

        result = approvals._forwarded_by([pm_item("WA-2", is_adhoc=True, adhoc_for="WA-1")])

        self.assertEqual(result, {})

    def test_no_ad_hoc_items_no_queries(self):
        get_all = self._use_get_all({})

        self.assertEqual(approvals._forwarded_by([pm_item("A"), pm_waiting("B")]), {})
        self.assertEqual(get_all.calls, [])


# ─── detail, apply and bulk ───────────────────────────────────────────────────


ME = "sara@example.com"
OWNER = "ali@example.com"


class FakeDoc:
    """The little of a `Document` the approvals code uses. Fields named in
    `hidden` sit above the user's permission level: they are on the document
    until `apply_fieldlevel_read_permissions()` removes them."""

    def __init__(self, doctype: str, name: str, owner: str = OWNER, hidden=(), **fields):
        self.doctype = doctype
        self.name = name
        self.owner = owner
        self._fields = {"doctype": doctype, "name": name, "owner": owner, **fields}
        self._hidden = set(hidden)
        self.can_read = lambda: True

    def check_permission(self, permtype="read"):
        """What `Document.check_permission` does when refused: the text goes
        to `flags.error_message` and a bare PermissionError is raised."""
        if permtype == "read" and not self.can_read():
            frappe.flags.error_message = f"You need the 'read' permission on {self.doctype} {self.name}"
            raise frappe.PermissionError

    def get(self, key, default=None):
        return self._fields.get(key, default)

    def as_dict(self) -> dict:
        return dict(self._fields)

    def apply_fieldlevel_read_permissions(self):
        for key in self._hidden:
            self._fields.pop(key, None)


def transition(action: str, **overrides) -> frappe._dict:
    """One PM Workflow Transition row, as `get_transitions` returns it."""
    row = {
        "state": "Pending Finance",
        "action": action,
        "next_state": "Approved",
        "require_comment": 0,
        "require_attachment": 0,
        "is_return_for_correction": 0,
        "priority": "Medium",
        "allow_self_approval": 0,
    }
    row.update(overrides)
    return frappe._dict(row)


def pm_action(name: str, **overrides) -> dict:
    """One PM Workflow Action row."""
    row = {
        "name": name,
        "status": "Open",
        "priority": "Medium",
        "workflow_state": "Pending Finance",
        "assigned_to": None,
        "for_submitter": OWNER,
        "completed_by": None,
        "is_adhoc": 0,
        "adhoc_for": None,
        "return_to_originator": 0,
    }
    row.update(overrides)
    return row


def pm_has_approval_access(user, doc, transition_row) -> bool:
    """PM's own rule (workflow.has_approval_access)."""
    return user == "Administrator" or bool(transition_row.get("allow_self_approval")) or user != doc.owner


def _field(fieldname: str, fieldtype: str = "Data", label: str = "", **attrs):
    return types.SimpleNamespace(fieldname=fieldname, fieldtype=fieldtype, label=label, **attrs)


def spec(action: str, **overrides) -> dict:
    """The ActionSpec the module should build for a transition."""
    row = {
        "action": action,
        "next_state": "Approved",
        "tone": "approve",
        "require_comment": False,
        "require_attachment": False,
        "is_return_for_correction": False,
        "priority": "Medium",
        "recommend_only": False,
    }
    row.update(overrides)
    return row


class DetailCase(ApiCase):
    """The signed-in user is sara; SINV-1 is a Sales Invoice raised by ali,
    waiting in "Pending Finance" with Approve and Reject (return for
    correction). Every read the code makes answers from the tables below."""

    def setUp(self):
        super().setUp()
        frappe.local.session.user = ME
        self.workflow = types.SimpleNamespace(
            name="SI Approval", workflow_state_field="workflow_state"
        )
        self.pm.get_workflow.return_value = self.workflow
        self.pm.hidden_doctypes.return_value = []
        self.pm.get_open_return_adhoc_action.return_value = None
        self.pm.get_transitions.return_value = [
            transition("Approve", priority="High"),
            transition("Reject", next_state="Draft", is_return_for_correction=1, require_comment=1),
        ]
        self.pm.has_approval_access.side_effect = pm_has_approval_access
        self.pm.transaction_label.side_effect = lambda doctype, is_return: (
            "Sales Return" if is_return else doctype
        )
        self.pm.get_document_lifecycle.return_value = {"chain": [], "roles": []}
        self.can_act: set[str] = set()
        self.pm.can_act_on.side_effect = lambda action_doc, user: (
            user == ME and action_doc.name in self.can_act
        )
        self.pm.apply_workflow.return_value = None

        self.doc = FakeDoc(
            "Sales Invoice",
            "SINV-1",
            hidden=("internal_margin",),
            workflow_state="Pending Finance",
            is_return=0,
            customer_name="Acme Trading",
            grand_total=1250.5,
            internal_margin=99.5,
            items=[{"item_name": "Steel Bar", "qty": 2, "amount": 1250.5}],
        )
        self.docs = {("Sales Invoice", "SINV-1"): self.doc}
        self.get_doc = self._patch("frappe.get_doc", side_effect=self._get_doc)

        self.readable = True
        self.unreadable_docs: set[str] = set()
        self.has_permission = self._patch(
            "frappe.has_permission",
            side_effect=lambda doctype, ptype="read", doc=None, **kwargs: self.readable,
        )
        fields = [
            _field("customer_name", label="Customer Name", bold=1),
            _field("grand_total", "Currency", label="Grand Total"),
            _field("internal_margin", "Currency", label="Internal Margin"),
            _field("items", "Table", label="Items"),
        ]
        names = {"customer_name", "grand_total", "currency", "company", "internal_margin", "items"}
        self._patch(
            "frappe.get_meta",
            return_value=types.SimpleNamespace(fields=fields, has_field=lambda f: f in names),
        )
        self._patch("vansale.steelforce.approvals.get_currency_precision", return_value=3)
        self._patch("frappe.get_cached_value", return_value="BHD")
        self.get_list = self._use_get_list(
            {
                "Sales Invoice": [
                    {"name": "SINV-1", "customer_name": "Acme Trading", "grand_total": 1250.5,
                     "currency": "BHD", "company": "Steel Co"}
                ]
            }
        )
        self.tables: dict[str, list] = {
            "PM Workflow Action": [],
            "User": [
                {"name": OWNER, "full_name": "Ali Hassan"},
                {"name": ME, "full_name": "Sara Khan"},
                {"name": "omar@example.com", "full_name": "Omar Saleh"},
            ],
            "File": [],
            "Comment": [],
            "PM Workflow Transition": [],
        }
        self.get_all = self._use_get_all(self.tables)
        frappe.local.db.get_value.side_effect = self._db_value
        self.new_state = "Approved"

    def _get_doc(self, doctype, name=None, *args, **kwargs):
        if doctype == "PM Workflow Action":
            return types.SimpleNamespace(doctype=doctype, name=name)
        if (doctype, name) not in self.docs:
            raise frappe.DoesNotExistError(f"{doctype} {name} not found")
        doc = self.docs[(doctype, name)]
        doc.can_read = lambda: self.readable and name not in self.unreadable_docs
        return doc

    def _db_value(self, doctype, name, fieldname, *args, **kwargs):
        if (doctype, fieldname) == ("Sales Invoice", "workflow_state") and (doctype, name) in self.docs:
            return self.new_state
        raise AssertionError(f"unexpected db.get_value({doctype!r}, {name!r}, {fieldname!r})")

    def _read_doctypes(self) -> list[str]:
        return [call[0] for call in self.get_all.calls]


class TestActionsFor(DetailCase):
    def test_a_self_owned_document_without_self_approval_has_no_actions(self):
        frappe.local.session.user = OWNER
        self.pm.get_transitions.return_value = [transition("Approve")]

        actions, banner = approvals._actions_for(self.doc, OWNER)

        self.assertEqual(actions, [])
        self.assertEqual(banner, "self_owned")
        self.pm.has_approval_access.assert_called_once_with(OWNER, self.doc, self.pm.get_transitions.return_value[0])

    def test_the_submitters_own_send_for_approval_stays_available(self):
        self.doc._fields["workflow_state"] = "Draft"
        self.pm.get_transitions.return_value = [
            transition("Send for Approval", state="Draft", next_state="Pending Finance",
                       allow_self_approval=1, require_attachment=1),
            transition("Approve", state="Draft"),
        ]

        actions, banner = approvals._actions_for(self.doc, OWNER)

        self.assertEqual(
            actions,
            [spec("Send for Approval", next_state="Pending Finance", require_attachment=True)],
        )
        self.assertIsNone(banner)

    def test_another_user_gets_every_transition_with_its_tone_and_flags(self):
        actions, banner = approvals._actions_for(self.doc, ME)

        self.assertEqual(
            actions,
            [
                spec("Approve", priority="High"),
                spec("Reject", next_state="Draft", tone="reject", require_comment=True,
                     is_return_for_correction=True),
            ],
        )
        self.assertIsNone(banner)
        self.pm.get_transitions.assert_called_once_with(self.doc)

    def test_a_return_to_me_recipient_gets_the_states_transitions_as_recommendations(self):
        self.pm.get_open_return_adhoc_action.return_value = "WA-9"
        self.pm.get_transitions.return_value = []
        self.tables["PM Workflow Transition"] = [
            transition("Approve"),
            transition("Reject", next_state="Draft", is_return_for_correction=1, require_comment=1),
        ]

        actions, banner = approvals._actions_for(self.doc, ME)

        self.assertEqual(banner, "recommend")
        self.assertEqual(
            actions,
            [
                spec("Approve", recommend_only=True),
                spec("Reject", next_state="Draft", tone="reject", require_comment=True,
                     is_return_for_correction=True, recommend_only=True),
            ],
        )
        self.pm.get_open_return_adhoc_action.assert_called_once_with(self.doc, "Pending Finance", ME)
        self.pm.get_transitions.assert_not_called()
        (doctype, kwargs), = [c for c in self.get_all.calls if c[0] == "PM Workflow Transition"]
        self.assertEqual(kwargs["filters"], {"parent": "SI Approval", "state": "Pending Finance"})

    def test_an_action_two_roles_share_shows_once_with_the_stricter_flags(self):
        self.pm.get_transitions.return_value = [
            transition("Approve"),
            transition("Approve", require_attachment=1),
        ]

        actions, _banner = approvals._actions_for(self.doc, ME)

        self.assertEqual(actions, [spec("Approve", require_attachment=True)])

    def test_a_blank_priority_falls_back_to_medium(self):
        self.pm.get_transitions.return_value = [transition("Approve", priority="")]

        actions, _banner = approvals._actions_for(self.doc, ME)

        self.assertEqual(actions[0]["priority"], "Medium")

    def test_no_transitions_at_all_is_no_actions_and_no_banner(self):
        self.pm.get_transitions.return_value = []

        self.assertEqual(approvals._actions_for(self.doc, ME), ([], None))


class TestDetail(DetailCase):
    def test_a_readable_document_gives_the_whole_detail(self):
        self.can_act.add("WA-1")
        self.tables["PM Workflow Action"] = [pm_action("WA-1", priority="High", assigned_to=ME)]
        self.tables["File"] = [
            {"name": "F-1", "file_url": "/private/files/quote.pdf", "is_private": 1},
            {"name": "F-2", "file_url": "/files/photo.jpg", "is_private": 0},
        ]
        self.tables["Comment"] = [
            {"owner": OWNER, "comment_email": OWNER, "comment_by": "",
             "content": "<p>Please <b>check</b> the rate &amp; qty</p>", "creation": datetime(2026, 11, 18, 14, 5, 9)},
        ]
        lifecycle = {
            "chain": [
                {"state": "Draft", "status": "done", "roles": ["Sales User"], "by": "Ali Hassan", "final": False},
                {"state": "Pending Finance", "status": "current", "roles": ["Finance Head"], "by": "", "final": False},
                {"state": "Approved", "status": "upcoming", "roles": [], "by": "", "final": True},
            ],
            "roles": [{"role": "Finance Head", "users": [{"user": ME, "full_name": "Sara Khan"}], "count": 1}],
            "events": [{"by": "Ali Hassan", "user": OWNER, "role": "", "state": "Draft",
                        "to_state": "Pending Finance", "action": "Draft to Pending Finance", "on": "18/11/26 14:00"}],
            "current": "Pending Finance",
            "finished": False,
            "something_else": "dropped",
        }
        self.pm.get_document_lifecycle.return_value = lifecycle

        result = approvals.detail("Sales Invoice", "SINV-1")

        self.assertEqual(
            result,
            {
                "doctype": "Sales Invoice",
                "docname": "SINV-1",
                "transaction": "Sales Invoice",
                "state": "Pending Finance",
                "priority": "High",
                "party": "Acme Trading",
                "amount": 1250.5,
                "currency": "BHD",
                "creator": "Ali Hassan",
                # the field above the user's permission level is not shown
                "facts": [
                    {"label": "Customer Name", "value": "Acme Trading"},
                    {"label": "Grand Total", "value": "1,250.500"},
                ],
                "lines": {"columns": ["Item", "Qty", "Amount"], "rows": [["Steel Bar", "2", "1,250.500"]], "total": 1},
                "attachments": [
                    {"name": "F-1", "url": "/private/files/quote.pdf", "is_private": True},
                    {"name": "F-2", "url": "/files/photo.jpg", "is_private": False},
                ],
                "has_attachment": True,
                "comments": [{"by": "Ali Hassan", "when": "18/11/26 14:05", "text": "Please check the rate & qty"}],
                "route": {k: v for k, v in lifecycle.items() if k != "something_else"},
                "actions": [
                    spec("Approve", priority="High"),
                    spec("Reject", next_state="Draft", tone="reject", require_comment=True,
                         is_return_for_correction=True),
                ],
                "action_id": "WA-1",
                "banner": None,
                "can_forward": True,
                "desk_url": "/app/sales-invoice/SINV-1",
            },
        )
        self.has_permission.assert_any_call("Sales Invoice", "read", doc="SINV-1")
        self.pm.get_document_lifecycle.assert_called_once_with("Sales Invoice", "SINV-1")
        self.assertEqual(frappe.local.message_log, [])

    def test_the_reads_are_scoped_to_the_document(self):
        approvals.detail("Sales Invoice", "SINV-1")

        calls = dict(self.get_all.calls)
        self.assertEqual(
            calls["PM Workflow Action"]["filters"],
            {"reference_doctype": "Sales Invoice", "reference_name": "SINV-1"},
        )
        self.assertEqual(
            calls["File"]["filters"], {"attached_to_doctype": "Sales Invoice", "attached_to_name": "SINV-1"}
        )
        self.assertEqual(
            calls["Comment"]["filters"],
            {"reference_doctype": "Sales Invoice", "reference_name": "SINV-1", "comment_type": "Workflow"},
        )
        self.assertEqual(calls["Comment"]["limit"], 20)
        self.assertEqual(calls["Comment"]["order_by"], "creation desc")

    def test_a_return_is_labelled_as_pm_labels_it(self):
        self.doc._fields["is_return"] = 1

        self.assertEqual(approvals.detail("Sales Invoice", "SINV-1")["transaction"], "Sales Return")

    def test_no_pm_action_means_medium_priority_no_forward_and_the_owner_as_creator(self):
        result = approvals.detail("Sales Invoice", "SINV-1")

        self.assertEqual(
            (result["priority"], result["action_id"], result["can_forward"], result["creator"]),
            ("Medium", None, False, "Ali Hassan"),
        )
        self.assertEqual((result["attachments"], result["has_attachment"]), ([], False))

    def test_a_lifecycle_without_a_workflow_fills_the_missing_keys(self):
        result = approvals.detail("Sales Invoice", "SINV-1")

        self.assertEqual(result["route"], {"chain": [], "roles": [], "events": [], "current": "", "finished": False})

    def test_cannot_read_but_holds_an_action_is_a_dead_end_without_leaks(self):
        self.readable = False
        self.can_act.add("WA-1")
        self.tables["PM Workflow Action"] = [pm_action("WA-1", priority="Critical", assigned_to=ME)]

        result = approvals.detail("Sales Invoice", "SINV-1")

        self.assertEqual(result["banner"], {"kind": "cannot_read"})
        self.assertEqual((result["party"], result["amount"], result["currency"]), ("", None, ""))
        self.assertEqual(result["actions"], [])
        self.assertEqual(result["facts"], [])
        self.assertEqual(result["lines"], {"columns": [], "rows": [], "total": 0})
        self.assertEqual((result["comments"], result["attachments"], result["has_attachment"]), ([], [], False))
        self.assertEqual(result["route"], {"chain": [], "roles": [], "events": [], "current": "", "finished": False})
        self.assertFalse(result["can_forward"])
        self.assertEqual((result["state"], result["priority"]), ("Pending Finance", "Critical"))
        self.assertEqual(result["desk_url"], "/app/sales-invoice/SINV-1")
        # nothing of the document was read
        self.assertEqual(self.get_list.calls, [])
        self.assertNotIn("Comment", self._read_doctypes())
        self.assertNotIn("File", self._read_doctypes())
        self.pm.get_transitions.assert_not_called()
        self.pm.get_document_lifecycle.assert_not_called()
        self.assertNotIn(("Sales Invoice", "SINV-1"), [c.args[:2] for c in self.get_doc.call_args_list])
        self.assertEqual(frappe.local.message_log, [])

    def test_cannot_read_and_holds_no_action_is_refused(self):
        self.readable = False
        self.tables["PM Workflow Action"] = [pm_action("WA-1", assigned_to="omar@example.com")]

        with self.assertRaises(frappe.PermissionError):
            approvals.detail("Sales Invoice", "SINV-1")
        self.pm.get_transitions.assert_not_called()
        self.assertNotIn("Comment", self._read_doctypes())

    def test_a_return_to_me_recipient_sees_who_forwarded_it_and_cannot_forward(self):
        self.can_act.add("WA-2")
        self.pm.get_open_return_adhoc_action.return_value = "WA-2"
        self.tables["PM Workflow Action"] = [
            pm_action("WA-2", assigned_to=ME, is_adhoc=1, adhoc_for="WA-1", return_to_originator=1),
            pm_action("WA-1", status="Forwarded", completed_by="omar@example.com"),
        ]
        self.tables["PM Workflow Transition"] = [transition("Approve")]

        result = approvals.detail("Sales Invoice", "SINV-1")

        self.assertEqual(result["banner"], {"kind": "recommend", "forwarder": "Omar Saleh"})
        self.assertEqual(result["actions"], [spec("Approve", recommend_only=True)])
        self.assertEqual(result["action_id"], "WA-2")
        self.assertFalse(result["can_forward"])

    def test_an_ad_hoc_recipient_without_return_to_me_can_forward(self):
        self.can_act.add("WA-2")
        self.tables["PM Workflow Action"] = [
            pm_action("WA-2", assigned_to=ME, is_adhoc=1, adhoc_for="WA-1", return_to_originator=0),
            pm_action("WA-1", status="Forwarded", completed_by="omar@example.com"),
        ]

        result = approvals.detail("Sales Invoice", "SINV-1")

        self.assertEqual(result["action_id"], "WA-2")
        self.assertTrue(result["can_forward"])
        self.assertIsNone(result["banner"])

    def test_a_forwarded_action_shows_who_holds_it_and_no_actions(self):
        self.can_act.add("WA-1")  # sara's own action, which she forwarded to omar
        self.tables["PM Workflow Action"] = [
            pm_action("WA-2", assigned_to="omar@example.com", is_adhoc=1, adhoc_for="WA-1"),
            pm_action("WA-1", status="Forwarded", assigned_to=ME, completed_by=ME),
        ]

        result = approvals.detail("Sales Invoice", "SINV-1")

        self.assertEqual(result["banner"], {"kind": "waiting", "holder": "Omar Saleh"})
        self.assertEqual(result["actions"], [])
        self.assertIsNone(result["action_id"])
        self.assertFalse(result["can_forward"])

    def test_the_submitter_sees_the_self_owned_banner(self):
        frappe.local.session.user = OWNER
        self.pm.get_transitions.return_value = [transition("Approve")]

        result = approvals.detail("Sales Invoice", "SINV-1")

        self.assertEqual(result["banner"], {"kind": "self_owned"})
        self.assertEqual(result["actions"], [])

    def test_a_missing_document_is_not_found(self):
        self.has_permission.side_effect = frappe.DoesNotExistError("Sales Invoice SINV-404 not found")

        with self.assertRaises(frappe.DoesNotExistError):
            approvals.detail("Sales Invoice", "SINV-404")


class TestApply(DetailCase):
    def test_a_return_for_correction_without_a_comment_is_refused_before_pm(self):
        with self.assertRaises(frappe.ValidationError) as caught:
            approvals.apply("Sales Invoice", "SINV-1", "Reject", comment="   ")

        self.assertEqual(str(caught.exception), "A comment is required for this action")
        self.pm.apply_workflow.assert_not_called()

    def test_a_required_attachment_is_refused_while_the_document_has_none(self):
        self.pm.get_transitions.return_value = [transition("Approve", require_attachment=1)]

        with self.assertRaises(frappe.ValidationError) as caught:
            approvals.apply("Sales Invoice", "SINV-1", "Approve")

        self.assertEqual(str(caught.exception), "Attach a file before this action")
        self.pm.apply_workflow.assert_not_called()

    def test_a_required_attachment_is_fine_once_a_file_is_attached(self):
        self.pm.get_transitions.return_value = [transition("Approve", require_attachment=1)]
        self.tables["File"] = [{"name": "F-1", "file_url": "/files/a.pdf", "is_private": 0}]

        self.assertTrue(approvals.apply("Sales Invoice", "SINV-1", "Approve")["ok"])
        self.pm.apply_workflow.assert_called_once()

    def test_an_action_the_document_does_not_offer_is_refused(self):
        with self.assertRaises(frappe.ValidationError) as caught:
            approvals.apply("Sales Invoice", "SINV-1", "Approve Cancellation", comment="ok")

        self.assertEqual(str(caught.exception), "This action is not available for this document")
        self.pm.apply_workflow.assert_not_called()

    def test_a_self_owned_document_cannot_be_approved_by_its_owner(self):
        frappe.local.session.user = OWNER
        self.pm.get_transitions.return_value = [transition("Approve")]

        with self.assertRaises(frappe.ValidationError):
            approvals.apply("Sales Invoice", "SINV-1", "Approve")
        self.pm.apply_workflow.assert_not_called()

    def test_an_allowed_action_goes_to_pm_and_returns_the_new_state(self):
        result = approvals.apply("Sales Invoice", "SINV-1", "Reject", comment="Wrong rate", priority="High")

        self.pm.apply_workflow.assert_called_once_with(self.doc.as_dict(), "Reject", "Wrong rate", "High")
        self.assertEqual(result, {"ok": True, "new_state": "Approved", "recommended": False})
        frappe.local.db.commit.assert_not_called()  # Frappe commits at the end of the POST

    def test_an_empty_comment_reaches_pm_as_none(self):
        approvals.apply("Sales Invoice", "SINV-1", "Approve")

        self.pm.apply_workflow.assert_called_once_with(self.doc.as_dict(), "Approve", None, None)  # no priority chosen: the transition default

    def test_a_recommendation_needs_no_comment_and_says_so(self):
        self.pm.get_open_return_adhoc_action.return_value = "WA-2"
        self.tables["PM Workflow Transition"] = [
            transition("Reject", next_state="Draft", is_return_for_correction=1, require_comment=1)
        ]
        self.new_state = "Pending Finance"  # PM records the answer; the document does not move

        result = approvals.apply("Sales Invoice", "SINV-1", "Reject")

        self.assertEqual(result, {"ok": True, "new_state": "Pending Finance", "recommended": True})
        self.pm.apply_workflow.assert_called_once_with(self.doc.as_dict(), "Reject", None, None)

    def test_a_pm_refusal_is_raised_verbatim_and_nothing_is_committed(self):
        self.pm.apply_workflow.side_effect = frappe.ValidationError("Invalid Workflow Action: Approve")

        with self.assertRaises(frappe.ValidationError) as caught:
            approvals.apply("Sales Invoice", "SINV-1", "Approve")

        self.assertEqual(str(caught.exception), "Invalid Workflow Action: Approve")
        frappe.local.db.commit.assert_not_called()

    def test_an_unknown_priority_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            approvals.apply("Sales Invoice", "SINV-1", "Approve", priority="Urgent")
        self.pm.apply_workflow.assert_not_called()

    def test_a_user_who_cannot_read_gets_pms_permission_error(self):
        self.pm.get_transitions.side_effect = frappe.PermissionError

        with self.assertRaises(frappe.PermissionError):
            approvals.apply("Sales Invoice", "SINV-1", "Approve")
        self.pm.apply_workflow.assert_not_called()


class TestApplyBulk(DetailCase):
    def setUp(self):
        super().setUp()
        for name in ("SINV-2", "SINV-3"):
            self.docs[("Sales Invoice", name)] = FakeDoc(
                "Sales Invoice", name, workflow_state="Pending Finance", is_return=0
            )

    def _db_calls(self) -> list[str]:
        return [c[0] for c in frappe.local.db.method_calls if c[0] in ("commit", "rollback")]

    def test_one_refusal_does_not_stop_the_batch(self):
        refusal = "Selling below the minimum price is not allowed for row 2 (Steel Bar)"

        def apply_workflow(doc, action, comment, priority):
            frappe.msgprint("a message from the document's own hooks")
            if doc["name"] == "SINV-2":
                raise frappe.ValidationError(refusal)

        self.pm.apply_workflow.side_effect = apply_workflow

        result = approvals.apply_bulk("Sales Invoice", '["SINV-1", "SINV-2", "SINV-3"]', "Approve")

        self.assertEqual(
            result,
            {
                "results": [
                    {"docname": "SINV-1", "ok": True, "message": ""},
                    {"docname": "SINV-2", "ok": False, "message": refusal},
                    {"docname": "SINV-3", "ok": True, "message": ""},
                ],
                "ok_count": 2,
                "failed_count": 1,
            },
        )
        self.assertEqual(self._db_calls(), ["commit", "rollback", "commit"])
        self.assertEqual(frappe.local.message_log, [])

    def test_more_than_twenty_documents_are_refused_before_anything_runs(self):
        names = frappe.as_json([f"SINV-{i}" for i in range(1, 22)])

        with self.assertRaises(frappe.ValidationError):
            approvals.apply_bulk("Sales Invoice", names, "Approve")
        self.pm.apply_workflow.assert_not_called()
        self.assertEqual(self._db_calls(), [])

    def test_duplicates_are_dropped_before_the_cap_and_the_loop(self):
        names = frappe.as_json(["SINV-1", "SINV-2", "SINV-1"] + ["SINV-3"] * 19)

        result = approvals.apply_bulk("Sales Invoice", names, "Approve")

        self.assertEqual([r["docname"] for r in result["results"]], ["SINV-1", "SINV-2", "SINV-3"])
        self.assertEqual(self.pm.apply_workflow.call_count, 3)

    def test_the_same_checks_as_a_single_apply_run_for_each_document(self):
        result = approvals.apply_bulk("Sales Invoice", '["SINV-1", "SINV-2"]', "Reject", comment="")

        self.assertEqual(result["failed_count"], 2)
        self.assertEqual(
            [r["message"] for r in result["results"]], ["A comment is required for this action"] * 2
        )
        self.pm.apply_workflow.assert_not_called()
        self.assertEqual(self._db_calls(), ["rollback", "rollback"])

    def test_a_bare_permission_error_reports_frappes_own_message(self):
        def get_transitions(doc):
            if doc.name == "SINV-2":
                frappe.flags.error_message = "You need the 'read' permission on Sales Invoice SINV-2"
                raise frappe.PermissionError
            return [transition("Approve")]

        self.pm.get_transitions.side_effect = get_transitions

        result = approvals.apply_bulk("Sales Invoice", '["SINV-2", "SINV-3"]', "Approve")

        self.assertEqual(
            result["results"],
            [
                {"docname": "SINV-2", "ok": False,
                 "message": "You need the 'read' permission on Sales Invoice SINV-2"},
                {"docname": "SINV-3", "ok": True, "message": ""},
            ],
        )

    def test_a_missing_document_fails_alone(self):
        result = approvals.apply_bulk("Sales Invoice", '["SINV-404", "SINV-1"]', "Approve")

        self.assertEqual([r["ok"] for r in result["results"]], [False, True])
        self.assertIn("SINV-404", result["results"][0]["message"])

    def test_names_must_be_a_list(self):
        with self.assertRaises(frappe.ValidationError):
            approvals.apply_bulk("Sales Invoice", '"SINV-1"', "Approve")


class TestWritesNeedPm(DetailCase):
    def test_detail_apply_and_bulk_refuse_without_pm(self):
        self.available.return_value = False

        for call in (
            lambda: approvals.detail("Sales Invoice", "SINV-1"),
            lambda: approvals.apply("Sales Invoice", "SINV-1", "Approve"),
            lambda: approvals.apply_bulk("Sales Invoice", '["SINV-1"]', "Approve"),
        ):
            with self.assertRaises(frappe.ValidationError):
                call()
        self.assertEqual(self.pm.mock_calls, [])


class TestReadCheckOnApply(DetailCase):
    """A "return to me" recipient's recommendations are built from the
    transition rows, not from PM's `get_transitions` (which checks read), so
    `apply` makes the read check itself."""

    def setUp(self):
        super().setUp()
        self.pm.get_open_return_adhoc_action.return_value = "WA-2"
        self.tables["PM Workflow Transition"] = [transition("Approve")]
        for name in ("SINV-2", "SINV-3"):
            self.docs[("Sales Invoice", name)] = FakeDoc(
                "Sales Invoice", name, workflow_state="Pending Finance", is_return=0
            )

    def test_a_return_to_me_recipient_who_cannot_read_is_refused(self):
        self.readable = False

        with self.assertRaises(frappe.PermissionError):
            approvals.apply("Sales Invoice", "SINV-1", "Approve")

        self.pm.apply_workflow.assert_not_called()
        self.pm.get_open_return_adhoc_action.assert_not_called()  # refused before the actions

    def test_a_return_to_me_recipient_who_can_read_still_recommends(self):
        self.assertEqual(
            approvals.apply("Sales Invoice", "SINV-1", "Approve"),
            {"ok": True, "new_state": "Approved", "recommended": True},
        )

    def test_in_bulk_the_unreadable_document_fails_with_the_permission_message(self):
        self.unreadable_docs.add("SINV-2")

        result = approvals.apply_bulk("Sales Invoice", '["SINV-1", "SINV-2", "SINV-3"]', "Approve")

        # the readable ones are advice only, which a batch never gives (below)
        self.assertEqual(
            result["results"],
            [
                {"docname": "SINV-1", "ok": False, "message": ADVICE_ONLY},
                {"docname": "SINV-2", "ok": False,
                 "message": "You need the 'read' permission on Sales Invoice SINV-2"},
                {"docname": "SINV-3", "ok": False, "message": ADVICE_ONLY},
            ],
        )
        self.pm.apply_workflow.assert_not_called()


ADVICE_ONLY = "Answer this one from its own screen"


class TestBulkNeverGivesAdvice(DetailCase):
    """A "return to me" recipient is asked for advice, not a decision: PM
    records the answer and the document does not move. A batch would report
    that as decided, so a batch refuses those documents and PM is not asked."""

    def setUp(self):
        super().setUp()
        self.docs[("Sales Invoice", "SINV-2")] = FakeDoc(
            "Sales Invoice", "SINV-2", workflow_state="Pending Finance", is_return=0
        )
        self.pm.get_open_return_adhoc_action.side_effect = lambda doc, state, user: (
            "WA-9" if doc.name == "SINV-2" else None
        )
        self.tables["PM Workflow Transition"] = [transition("Approve")]

    def test_an_advice_only_document_fails_alone_and_pm_is_not_asked_for_it(self):
        result = approvals.apply_bulk("Sales Invoice", '["SINV-1", "SINV-2"]', "Approve")

        self.assertEqual(
            result,
            {
                "results": [
                    {"docname": "SINV-1", "ok": True, "message": ""},
                    {"docname": "SINV-2", "ok": False, "message": ADVICE_ONLY},
                ],
                "ok_count": 1,
                "failed_count": 1,
            },
        )
        self.assertEqual([c.args[0]["name"] for c in self.pm.apply_workflow.call_args_list], ["SINV-1"])

    def test_a_single_apply_still_gives_the_advice(self):
        result = approvals.apply("Sales Invoice", "SINV-2", "Approve")

        self.assertTrue(result["recommended"])
        self.pm.apply_workflow.assert_called_once()


class TestBulkHardening(DetailCase):
    """One document's trouble stays that document's: unexpected errors are
    logged (deferred: the batch rolls back), a failing rollback or commit
    does not end the batch, a label left by an earlier document never names
    a later one, and row messages are plain text."""

    def setUp(self):
        super().setUp()
        for name in ("SINV-2", "SINV-3"):
            self.docs[("Sales Invoice", name)] = FakeDoc(
                "Sales Invoice", name, workflow_state="Pending Finance", is_return=0
            )
        self.log_error = self._patch("frappe.log_error")

    def _bulk(self, names='["SINV-1", "SINV-2", "SINV-3"]'):
        return approvals.apply_bulk("Sales Invoice", names, "Approve")

    def test_an_unexpected_error_is_logged_deferred_and_the_batch_goes_on(self):
        def apply_workflow(doc, action, comment, priority):
            if doc["name"] == "SINV-2":
                raise KeyError("grand_total")

        self.pm.apply_workflow.side_effect = apply_workflow

        result = self._bulk()

        self.assertEqual(
            result["results"],
            [
                {"docname": "SINV-1", "ok": True, "message": ""},
                # never the exception's own text, which can show internals
                {"docname": "SINV-2", "ok": False, "message": "Could not apply this document. It was logged."},
                {"docname": "SINV-3", "ok": True, "message": ""},
            ],
        )
        self.log_error.assert_called_once()
        self.assertTrue(self.log_error.call_args.kwargs.get("defer_insert"))

    def test_the_generic_message_for_an_unexpected_error_is_translated(self):
        self._patch("vansale.steelforce.approvals._", side_effect=lambda text: f"ar:{text}")
        self.pm.apply_workflow.side_effect = AttributeError("'NoneType' object has no attribute 'rate'")

        result = self._bulk('["SINV-1"]')

        self.assertEqual(result["results"][0]["message"], "ar:Could not apply this document. It was logged.")
        self.assertNotIn("NoneType", result["results"][0]["message"])

    def test_a_failing_commit_shows_the_generic_message(self):
        frappe.local.db.commit.side_effect = Exception("Deadlock found when trying to get lock")

        result = self._bulk('["SINV-1"]')

        self.assertEqual(result["results"][0]["message"], "Could not apply this document. It was logged.")
        self.log_error.assert_called_once()

    def test_a_refusal_is_not_logged(self):
        self.pm.apply_workflow.side_effect = frappe.ValidationError("Invalid Workflow Action: Approve")

        self._bulk()

        self.log_error.assert_not_called()

    def test_a_permission_refusal_is_not_logged(self):
        self.unreadable_docs.add("SINV-2")

        self._bulk()

        self.log_error.assert_not_called()

    def test_a_rollback_that_fails_does_not_end_the_batch(self):
        self.pm.apply_workflow.side_effect = lambda doc, *a: (
            (_ for _ in ()).throw(frappe.ValidationError("no")) if doc["name"] == "SINV-1" else None
        )
        frappe.local.db.rollback.side_effect = Exception("Lost connection to MySQL server")

        result = self._bulk()

        self.assertEqual(
            result["results"],
            [
                {"docname": "SINV-1", "ok": False, "message": "no"},
                {"docname": "SINV-2", "ok": True, "message": ""},
                {"docname": "SINV-3", "ok": True, "message": ""},
            ],
        )

    def test_a_commit_that_fails_reports_that_document_failed_and_the_batch_goes_on(self):
        commits = iter([None, Exception("Deadlock found when trying to get lock"), None])

        def commit():
            outcome = next(commits)
            if outcome:
                raise outcome

        frappe.local.db.commit.side_effect = commit

        result = self._bulk()

        self.assertEqual([r["ok"] for r in result["results"]], [True, False, True])
        self.assertEqual(result["ok_count"], 2)
        self.assertEqual(
            [c[0] for c in frappe.local.db.method_calls if c[0] in ("commit", "rollback")],
            ["commit", "commit", "rollback", "commit"],
        )

    def test_a_label_left_by_an_earlier_document_never_names_a_later_one(self):
        def apply_workflow(doc, action, comment, priority):
            if doc["name"] == "SINV-1":
                frappe.flags.error_message = "You need the 'write' permission on Sales Invoice SINV-1"
                raise frappe.ValidationError("Selling below the minimum price")
            if doc["name"] == "SINV-2":
                raise frappe.PermissionError  # bare, and it set no label of its own

        self.pm.apply_workflow.side_effect = apply_workflow

        result = self._bulk('["SINV-1", "SINV-2"]')

        self.assertEqual(
            [r["message"] for r in result["results"]],
            ["Selling below the minimum price", "The action could not be applied"],
        )

    def test_a_stale_label_from_before_the_batch_is_not_reported(self):
        frappe.flags.error_message = "left over from earlier in the request"
        self.pm.apply_workflow.side_effect = frappe.PermissionError

        result = self._bulk('["SINV-1"]')

        self.assertEqual(result["results"][0]["message"], "The action could not be applied")

    def test_row_messages_are_plain_text(self):
        self.pm.apply_workflow.side_effect = frappe.ValidationError(
            "Row <b>2</b>: rate &lt; minimum for <strong>Steel &amp; Bar</strong>"
        )

        result = self._bulk('["SINV-1"]')

        self.assertEqual(result["results"][0]["message"], "Row 2: rate < minimum for Steel & Bar")

    def test_a_single_apply_raises_the_message_unchanged(self):
        text = "Row <b>2</b>: rate &lt; minimum"
        self.pm.apply_workflow.side_effect = frappe.ValidationError(text)

        with self.assertRaises(frappe.ValidationError) as caught:
            approvals.apply("Sales Invoice", "SINV-1", "Approve")

        self.assertEqual(str(caught.exception), text)
        self.log_error.assert_not_called()


class TestHiddenTypesAreRefused(DetailCase):
    """Stock Entry and every type PM hides from its inbox (`_hidden_doctypes()`:
    any workflow of the type flagged `hide_from_approval_inbox`, active or
    not) never appear here: every endpoint refuses them before reading or
    applying."""

    def setUp(self):
        super().setUp()
        self.docs[("Stock Entry", "STE-1")] = FakeDoc("Stock Entry", "STE-1", workflow_state="Pending")

    def _assert_nothing_happened(self):
        self.has_permission.assert_not_called()
        self.get_doc.assert_not_called()
        self.assertEqual(self.get_all.calls, [])
        self.assertEqual(self.get_list.calls, [])
        self.pm.get_workflow.assert_not_called()
        self.pm.get_transitions.assert_not_called()
        self.pm.apply_workflow.assert_not_called()
        self.pm.get_document_lifecycle.assert_not_called()
        self.assertEqual(
            [c[0] for c in frappe.local.db.method_calls if c[0] in ("commit", "rollback")], []
        )
        self.assertEqual(frappe.local.message_log, [])

    def _endpoints(self, doctype: str, name: str):
        return {
            "detail": lambda: approvals.detail(doctype, name),
            "apply": lambda: approvals.apply(doctype, name, "Approve"),
            "apply_bulk": lambda: approvals.apply_bulk(doctype, frappe.as_json([name]), "Approve"),
        }

    def test_stock_entry_is_refused_by_every_endpoint(self):
        for endpoint, call in self._endpoints("Stock Entry", "STE-1").items():
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(frappe.PermissionError):
                    call()
                self._assert_nothing_happened()

    def test_a_type_pm_hides_is_refused_even_when_its_governing_workflow_is_not_flagged(self):
        # Two workflows for Sales Invoice: the one PM would pick for SINV-1 is
        # not flagged; another one (inactive, or for another company) is. PM
        # hides the type, so the approvals do too.
        self.pm.hidden_doctypes.return_value = ["Sales Invoice", "Gate Pass"]
        self.workflow.hide_from_approval_inbox = 0

        for endpoint, call in self._endpoints("Sales Invoice", "SINV-1").items():
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(frappe.PermissionError):
                    call()
                self._assert_nothing_happened()
        self.pm.hidden_doctypes.assert_called_with()

    def test_the_type_is_compared_without_regard_to_case(self):
        # the database finds "stock entry" as Stock Entry, so the refusal must too
        self.pm.hidden_doctypes.return_value = ["gate PASS"]
        self.docs[("stock entry", "STE-1")] = FakeDoc("stock entry", "STE-1", workflow_state="Pending")
        self.docs[("Gate Pass", "GP-1")] = FakeDoc("Gate Pass", "GP-1", workflow_state="Pending")

        for doctype, name in (("stock entry", "STE-1"), ("STOCK ENTRY", "STE-1"), ("Gate Pass", "GP-1")):
            for endpoint, call in self._endpoints(doctype, name).items():
                with self.subTest(doctype=doctype, endpoint=endpoint):
                    with self.assertRaises(frappe.PermissionError):
                        call()
                    self._assert_nothing_happened()

    def test_an_ordinary_type_is_unaffected(self):
        self.pm.hidden_doctypes.return_value = ["Gate Pass"]

        self.assertEqual(approvals.detail("Sales Invoice", "SINV-1")["docname"], "SINV-1")
        self.assertTrue(approvals.apply("Sales Invoice", "SINV-1", "Approve")["ok"])
        self.assertEqual(
            approvals.apply_bulk("Sales Invoice", '["SINV-1"]', "Approve")["ok_count"], 1
        )
        self.pm.get_workflow.assert_called_with("Sales Invoice", docname="SINV-1", doc=self.doc, throw=False)


class TestTheWorkflowFollowsTheDocument(DetailCase):
    """A type can have several workflows (a standard one and an Oman one, say).
    PM picks the one that governs a document from the document itself, so the
    lookup is given the document, and its transitions and state field are used."""

    def setUp(self):
        super().setUp()
        self.oman = types.SimpleNamespace(name="SI Oman", workflow_state_field="custom_oman_status")
        self.doc._fields.update(company="Steel Oman", custom_oman_status="Pending GM")

        def get_workflow(doctype, docname=None, doc=None, throw=True):
            if doc is not None and doc.get("company") == "Steel Oman":
                return self.oman
            return self.workflow  # the viewer's default company

        self.pm.get_workflow.side_effect = get_workflow
        self.pm.get_open_return_adhoc_action.return_value = "WA-2"
        self.tables["PM Workflow Transition"] = [transition("Approve", state="Pending GM")]

    def _db_value(self, doctype, name, fieldname, *args, **kwargs):
        if (doctype, name, fieldname) == ("Sales Invoice", "SINV-1", "custom_oman_status"):
            return "Pending GM"
        raise AssertionError(f"unexpected db.get_value({doctype!r}, {name!r}, {fieldname!r})")

    def test_apply_reads_the_documents_own_workflow(self):
        result = approvals.apply("Sales Invoice", "SINV-1", "Approve")

        self.assertEqual(result, {"ok": True, "new_state": "Pending GM", "recommended": True})
        self.pm.get_workflow.assert_called_with("Sales Invoice", docname="SINV-1", doc=self.doc, throw=False)
        self.pm.get_open_return_adhoc_action.assert_called_once_with(self.doc, "Pending GM", ME)
        (_doctype, kwargs), = [c for c in self.get_all.calls if c[0] == "PM Workflow Transition"]
        self.assertEqual(kwargs["filters"], {"parent": "SI Oman", "state": "Pending GM"})

    def test_detail_shows_the_documents_own_state_and_actions(self):
        result = approvals.detail("Sales Invoice", "SINV-1")

        self.assertEqual(result["state"], "Pending GM")
        self.assertEqual(result["actions"], [spec("Approve", recommend_only=True)])
        self.pm.get_workflow.assert_called_with("Sales Invoice", docname="SINV-1", doc=self.doc, throw=False)

    def test_the_expected_state_is_compared_with_the_workflows_own_state_field(self):
        self.assertTrue(approvals.apply("Sales Invoice", "SINV-1", "Approve", expected_state="Pending GM")["ok"])

        self.pm.apply_workflow.reset_mock()
        # `workflow_state` says "Pending Finance" too, but this workflow keeps its state elsewhere
        self.doc._fields["workflow_state"] = "Pending Finance"
        with self.assertRaises(frappe.ValidationError) as caught:
            approvals.apply("Sales Invoice", "SINV-1", "Approve", expected_state="Pending Finance")
        self.assertEqual(str(caught.exception), CHANGED)
        self.pm.apply_workflow.assert_not_called()


CHANGED = "This document changed since you opened it. Review it again."


class TestExpectedState(DetailCase):
    """The approver decided on what they saw: `expected_state` is the state the
    document was in when it was opened (or listed, for a batch). A document
    that moved since is refused before PM is asked to do anything."""

    def setUp(self):
        super().setUp()
        for name in ("SINV-2", "SINV-3"):
            self.docs[("Sales Invoice", name)] = FakeDoc(
                "Sales Invoice", name, workflow_state="Pending Finance", is_return=0
            )

    def test_the_state_it_was_opened_in_goes_ahead(self):
        result = approvals.apply("Sales Invoice", "SINV-1", "Approve", expected_state="Pending Finance")

        self.assertTrue(result["ok"])
        self.pm.apply_workflow.assert_called_once()

    def test_a_document_that_moved_since_it_was_opened_is_refused_before_pm(self):
        with self.assertRaises(frappe.ValidationError) as caught:
            approvals.apply("Sales Invoice", "SINV-1", "Approve", expected_state="Draft")

        self.assertEqual(str(caught.exception), CHANGED)
        self.pm.apply_workflow.assert_not_called()
        self.pm.get_transitions.assert_not_called()
        self.pm.get_open_return_adhoc_action.assert_not_called()

    def test_no_expected_state_means_no_check(self):
        self.doc._fields["workflow_state"] = "Something Else"
        self.pm.get_transitions.return_value = [transition("Approve", state="Something Else")]

        self.assertTrue(approvals.apply("Sales Invoice", "SINV-1", "Approve")["ok"])
        self.assertTrue(approvals.apply("Sales Invoice", "SINV-1", "Approve", expected_state="")["ok"])

    def test_the_state_is_not_revealed_to_someone_who_cannot_read_the_document(self):
        self.readable = False

        with self.assertRaises(frappe.PermissionError):
            approvals.apply("Sales Invoice", "SINV-1", "Approve", expected_state="Draft")
        self.pm.apply_workflow.assert_not_called()

    def test_in_a_batch_a_moved_document_fails_alone_and_an_unlisted_one_is_not_checked(self):
        self.docs[("Sales Invoice", "SINV-3")]._fields["workflow_state"] = "Approved"
        self.pm.get_transitions.return_value = [transition("Approve")]
        states = frappe.as_json({"SINV-1": "Pending Finance", "SINV-2": "Draft"})

        result = approvals.apply_bulk(
            "Sales Invoice", '["SINV-1", "SINV-2", "SINV-3"]', "Approve", expected_states=states
        )

        self.assertEqual(
            result["results"],
            [
                {"docname": "SINV-1", "ok": True, "message": ""},
                {"docname": "SINV-2", "ok": False, "message": CHANGED},
                {"docname": "SINV-3", "ok": True, "message": ""},  # not in the map: not checked
            ],
        )
        self.assertEqual(
            [c.args[0]["name"] for c in self.pm.apply_workflow.call_args_list], ["SINV-1", "SINV-3"]
        )

    def test_expected_states_that_are_not_an_object_are_refused_before_anything_runs(self):
        for bad in ('["SINV-1"]', '"Draft"', "not json"):
            with self.subTest(bad=bad):
                with self.assertRaises(frappe.ValidationError):
                    approvals.apply_bulk("Sales Invoice", '["SINV-1"]', "Approve", expected_states=bad)
        self.pm.apply_workflow.assert_not_called()
        self.assertEqual([c[0] for c in frappe.local.db.method_calls if c[0] in ("commit", "rollback")], [])


class TestPriorityAndComment(DetailCase):
    """A blank priority is "not chosen": PM then uses the transition's own
    default. A comment of only spaces is no comment."""

    def setUp(self):
        super().setUp()
        self.docs[("Sales Invoice", "SINV-2")] = FakeDoc(
            "Sales Invoice", "SINV-2", workflow_state="Pending Finance", is_return=0
        )

    def test_no_priority_reaches_pm_as_none(self):
        approvals.apply("Sales Invoice", "SINV-1", "Approve")
        approvals.apply("Sales Invoice", "SINV-1", "Approve", priority="")
        approvals.apply("Sales Invoice", "SINV-1", "Approve", priority="  ")

        self.assertEqual([c.args[3] for c in self.pm.apply_workflow.call_args_list], [None, None, None])

    def test_a_chosen_priority_reaches_pm(self):
        for priority in ("Low", "Medium", "High", "Critical"):
            with self.subTest(priority=priority):
                self.pm.apply_workflow.reset_mock()
                approvals.apply("Sales Invoice", "SINV-1", "Approve", priority=priority)
                self.assertEqual(self.pm.apply_workflow.call_args.args[3], priority)

    def test_in_a_batch_no_priority_reaches_pm_as_none(self):
        approvals.apply_bulk("Sales Invoice", '["SINV-1", "SINV-2"]', "Approve")

        self.assertEqual([c.args[3] for c in self.pm.apply_workflow.call_args_list], [None, None])

    def test_an_unknown_priority_is_refused_in_a_batch_before_anything_runs(self):
        with self.assertRaises(frappe.ValidationError):
            approvals.apply_bulk("Sales Invoice", '["SINV-1"]', "Approve", priority="Urgent")
        self.pm.apply_workflow.assert_not_called()

    def test_a_comment_of_spaces_reaches_pm_as_none_and_a_comment_is_trimmed(self):
        approvals.apply("Sales Invoice", "SINV-1", "Approve", comment="   \n ")
        approvals.apply("Sales Invoice", "SINV-1", "Approve", comment="  fine by me \n")

        self.assertEqual(
            [c.args[2] for c in self.pm.apply_workflow.call_args_list], [None, "fine by me"]
        )

    def test_in_a_batch_a_comment_of_spaces_reaches_pm_as_none(self):
        approvals.apply_bulk("Sales Invoice", '["SINV-1"]', "Approve", comment="   ")

        self.pm.apply_workflow.assert_called_once_with(self.docs[("Sales Invoice", "SINV-1")].as_dict(), "Approve", None, None)


if __name__ == "__main__":
    unittest.main()
