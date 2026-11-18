"""Forward, attach, my requests, sent back and history
(`vansale.steelforce.approvals_extra`) without a site and without
`permission_manager` (PM): every PM call goes through `approvals._pm()`, which
these tests replace, and every database read is a stub that answers from a
table the test writes down (an unexpected read fails the test).

Run: cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale \
     ../env/bin/python -m unittest vansale.tests.test_approvals_extra -v
"""

from __future__ import annotations

import types
import unittest
from collections import Counter
from datetime import datetime
from unittest.mock import MagicMock, call

import frappe
import pymysql

from vansale.steelforce import approvals, approvals_extra
from vansale.tests.test_approvals_api import ME, OWNER, FakeDoc, SiteFreeCase

PM_ACTION = approvals.PM_ACTION
PM_TRANSITION = approvals.PM_TRANSITION
PM_ROLE = "PM Workflow Action Permitted Role"

OMAR = "omar@example.com"
FATIMA = "fatima@example.com"


class Reader:
    """A stand-in for `frappe.get_all` that answers each doctype from a handler
    (a list of rows, or a function of the call's keyword arguments) and fails on
    any other doctype. `.calls` lists `(doctype, kwargs)` for every call."""

    def __init__(self):
        self.handlers: dict = {}
        self.calls: list = []

    def __call__(self, doctype, *args, **kwargs):
        self.calls.append((doctype, kwargs))
        if doctype not in self.handlers:
            raise AssertionError(f"unexpected get_all({doctype!r}, {kwargs})")
        handler = self.handlers[doctype]
        rows = handler(kwargs) if callable(handler) else handler
        return [frappe._dict(row) for row in rows]

    def of(self, doctype: str) -> list[dict]:
        return [kwargs for name, kwargs in self.calls if name == doctype]

    def count(self, doctype: str) -> int:
        return len(self.of(doctype))


class ExtraCase(SiteFreeCase):
    """PM is installed (stubbed as `self.pm`), the signed-in user is sara and
    any `get_all` the test did not provide for fails it."""

    def setUp(self):
        super().setUp()
        frappe.local.session.user = ME
        self.available = self._patch("vansale.steelforce.approvals.is_available", return_value=True)
        self.pm = MagicMock(name="pm")
        self.pm.hidden_doctypes.return_value = []
        self._patch("vansale.steelforce.approvals._pm", return_value=self.pm)
        self.reader = Reader()
        self._patch("frappe.get_all", self.reader)
        # frappe.db is a MagicMock here; give it the driver's real error classes.
        for name in ("ProgrammingError", "OperationalError", "InternalError", "DataError"):
            setattr(frappe.local.db, name, getattr(pymysql, name))

    def assert_nothing_happened(self):
        """A refusal leaves no read, no database call and no message behind."""
        self.assertEqual(self.reader.calls, [])
        self.assertEqual(frappe.local.db.method_calls, [])
        self.assertEqual(frappe.local.message_log, [])


# ─── the seven endpoints ──────────────────────────────────────────────────────


class TestEndpointsAreWhitelisted(unittest.TestCase):
    VERBS = {
        "forward_targets": "GET",
        "forward": "POST",
        "return_to_originator": "POST",
        "attach": "POST",
        "my_requests": "GET",
        "sent_back": "GET",
        "history": "GET",
    }

    def test_each_endpoint_answers_its_verb_only_and_is_documented(self):
        for name, verb in self.VERBS.items():
            function = getattr(approvals_extra, name)
            with self.subTest(endpoint=name):
                self.assertIn(function, frappe.whitelisted)
                self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[function], [verb])
                self.assertNotIn(function, frappe.guest_methods)
                self.assertTrue((function.__doc__ or "").strip())


# ─── forward_targets ──────────────────────────────────────────────────────────


def people(*names: str) -> list[dict]:
    return [{"name": name, "full_name": name.split("@")[0].title()} for name in names]


class ForwardTargetsCase(ExtraCase):
    """SINV-1 is a Sales Invoice waiting in "Pending Finance"; sara may read it.
    Who the candidates are, who may read it and what the workflow's transitions
    and the users' roles say are set on the case before the call."""

    def setUp(self):
        super().setUp()
        self.doc = FakeDoc("Sales Invoice", "SINV-1", workflow_state="Pending Finance")
        self.get_doc = self._patch("frappe.get_doc", side_effect=self._get_doc)
        self.readers: set[str] | None = None  # None: everybody may read it
        self.has_permission = self._patch(
            "frappe.has_permission",
            side_effect=lambda doctype, ptype="read", doc=None, user=None, **kw: (
                self.readers is None or user in self.readers
            ),
        )
        self.workflow = types.SimpleNamespace(name="SI Approval", workflow_state_field="workflow_state")
        self.pm.get_workflow.return_value = self.workflow

        self.candidates: list[dict] = []
        self.transition_roles: list[str] = []
        self.role_rows: list[dict] = []
        self.reader.handlers["User"] = lambda kwargs: self.candidates
        self.reader.handlers[PM_TRANSITION] = lambda kwargs: [
            {"allowed": role} for role in self.transition_roles
        ]
        self.reader.handlers["Has Role"] = lambda kwargs: self.role_rows

    def _get_doc(self, doctype, name=None, *args, **kwargs):
        if (doctype, name) != ("Sales Invoice", "SINV-1"):
            raise frappe.DoesNotExistError(f"{doctype} {name} not found")
        return self.doc

    def targets(self, query: str = "") -> list[dict]:
        return approvals_extra.forward_targets("Sales Invoice", "SINV-1", query)

    def checked_users(self) -> list[str]:
        return [c.kwargs["user"] for c in self.has_permission.call_args_list]


class TestForwardTargets(ForwardTargetsCase):
    def test_a_candidate_who_cannot_read_the_document_is_dropped(self):
        self.candidates = people("ali@example.com", "bela@example.com", "chen@example.com")
        self.readers = {"ali@example.com", "chen@example.com"}

        result = self.targets()

        self.assertEqual([row["user"] for row in result], ["ali@example.com", "chen@example.com"])
        # each candidate is judged on the document, as that candidate
        self.assertEqual(self.checked_users(), ["ali@example.com", "bela@example.com", "chen@example.com"])
        for each in self.has_permission.call_args_list:
            self.assertEqual(each.args, ("Sales Invoice", "read"))
            self.assertIs(each.kwargs["doc"], self.doc)

    def test_never_more_than_twenty_and_nobody_is_checked_after_the_twentieth(self):
        self.candidates = people(*(f"u{n:02d}@example.com" for n in range(30)))

        result = self.targets()

        self.assertEqual(
            [row["user"] for row in result], [f"u{n:02d}@example.com" for n in range(20)]
        )
        self.assertEqual(len(self.checked_users()), 20)

    def test_the_read_check_is_made_on_a_batch_of_a_hundred_before_the_cut_to_twenty(self):
        self.candidates = people(*(f"u{n:03d}@example.com" for n in range(100)))
        self.readers = {f"u{n:03d}@example.com" for n in (97, 98, 99)}

        result = self.targets()

        # the first ninety-seven cannot read it: they must not use up the twenty
        self.assertEqual([row["user"] for row in result], [f"u{n:03d}@example.com" for n in (97, 98, 99)])
        (kwargs,) = self.reader.of("User")
        self.assertEqual(kwargs["limit"], 100)

    def test_the_candidate_read_is_enabled_system_users_without_the_caller_or_the_standard_users(self):
        self.candidates = people("ali@example.com")

        self.targets()

        (kwargs,) = self.reader.of("User")
        self.assertEqual(
            kwargs["filters"],
            {"enabled": 1, "user_type": "System User", "name": ["not in", ["Guest", "Administrator", ME]]},
        )
        self.assertEqual(kwargs["fields"], ["name", "full_name"])
        self.assertEqual(kwargs["order_by"], "full_name asc, name asc")

    def test_a_query_matches_the_user_id_or_the_full_name(self):
        self.candidates = people("ali@example.com")

        self.targets("  ali ")

        (kwargs,) = self.reader.of("User")
        self.assertEqual(
            kwargs["or_filters"], {"name": ["like", "%ali%"], "full_name": ["like", "%ali%"]}
        )

    def test_no_query_means_no_name_filter(self):
        self.candidates = people("ali@example.com")

        self.targets("")
        self.targets("   ")

        for kwargs in self.reader.of("User"):
            self.assertFalse(kwargs.get("or_filters"))

    def test_a_result_is_user_full_name_and_role_only(self):
        self.candidates = [{"name": "ali@example.com", "full_name": "Ali Hassan"}]

        self.assertEqual(
            self.targets(), [{"user": "ali@example.com", "full_name": "Ali Hassan", "role": ""}]
        )

    def test_a_user_without_a_full_name_shows_the_user_id(self):
        self.candidates = [{"name": "ali@example.com", "full_name": None}]

        self.assertEqual(self.targets()[0]["full_name"], "ali@example.com")

    def test_the_role_is_the_candidates_first_role_on_the_states_transitions(self):
        self.candidates = people("ali@example.com", "bela@example.com", "chen@example.com", "dana@example.com")
        self.readers = {"ali@example.com", "bela@example.com", "chen@example.com"}
        self.transition_roles = ["Finance Head", "Finance Head", "General Manager"]
        # what the read returns: the roles of the users asked about that are
        # on the transitions, in each user's own order
        self.role_rows = [
            {"parent": "ali@example.com", "role": "General Manager"},
            {"parent": "ali@example.com", "role": "Finance Head"},
            {"parent": "bela@example.com", "role": "Finance Head"},
        ]

        result = {row["user"]: row["role"] for row in self.targets()}

        self.assertEqual(
            result,
            {"ali@example.com": "General Manager", "bela@example.com": "Finance Head", "chen@example.com": ""},
        )
        (transitions,) = self.reader.of(PM_TRANSITION)
        self.assertEqual(
            transitions["filters"], {"parent": "SI Approval", "state": "Pending Finance", "approver_type": "Role"}
        )
        # only the people who are returned, and only the roles on the transitions
        (roles,) = self.reader.of("Has Role")
        self.assertEqual(
            roles["filters"],
            {
                "parenttype": "User",
                "parent": ["in", ["ali@example.com", "bela@example.com", "chen@example.com"]],
                "role": ["in", ["Finance Head", "General Manager"]],
            },
        )
        self.assertEqual(roles["order_by"], "idx asc")

    def test_the_workflow_and_state_come_from_the_document_itself(self):
        self.candidates = people("ali@example.com")
        self.pm.get_workflow.return_value = types.SimpleNamespace(
            name="SI Oman", workflow_state_field="custom_oman_status"
        )
        self.doc._fields.update(custom_oman_status="Pending GM")
        self.transition_roles = ["General Manager"]
        self.role_rows = [{"parent": "ali@example.com", "role": "General Manager"}]

        result = self.targets()

        self.pm.get_workflow.assert_called_once_with("Sales Invoice", docname="SINV-1", doc=self.doc, throw=False)
        (transitions,) = self.reader.of(PM_TRANSITION)
        self.assertEqual(transitions["filters"]["parent"], "SI Oman")
        self.assertEqual(transitions["filters"]["state"], "Pending GM")
        self.assertEqual(result[0]["role"], "General Manager")

    def test_no_workflow_for_the_document_means_no_roles_and_no_role_reads(self):
        self.candidates = people("ali@example.com")
        self.pm.get_workflow.return_value = None

        self.assertEqual(self.targets()[0]["role"], "")
        self.assertEqual(self.reader.count(PM_TRANSITION), 0)
        self.assertEqual(self.reader.count("Has Role"), 0)

    def test_a_state_with_no_role_transitions_means_no_role_read(self):
        self.candidates = people("ali@example.com")
        self.transition_roles = []

        self.assertEqual(self.targets()[0]["role"], "")
        self.assertEqual(self.reader.count("Has Role"), 0)

    def test_nobody_who_can_read_it_means_no_role_reads(self):
        self.candidates = people("ali@example.com")
        self.readers = set()
        self.transition_roles = ["Finance Head"]

        self.assertEqual(self.targets(), [])
        self.assertEqual(self.reader.count(PM_TRANSITION), 0)
        self.assertEqual(self.reader.count("Has Role"), 0)


class TestForwardTargetsRefusals(ForwardTargetsCase):
    def test_stock_entry_is_refused_before_anything_is_read(self):
        with self.assertRaises(frappe.PermissionError):
            approvals_extra.forward_targets("Stock Entry", "STE-1")

        self.assert_nothing_happened()
        self.get_doc.assert_not_called()
        self.has_permission.assert_not_called()
        self.assertEqual(self.pm.method_calls, [])

    def test_a_type_pm_hides_is_refused_before_anything_is_read(self):
        self.pm.hidden_doctypes.return_value = ["Sales Invoice"]

        with self.assertRaises(frappe.PermissionError):
            self.targets()

        self.assert_nothing_happened()
        self.get_doc.assert_not_called()
        self.has_permission.assert_not_called()

    def test_a_caller_who_cannot_read_the_document_is_refused_and_no_user_is_listed(self):
        self.doc.can_read = lambda: False
        self.candidates = people("ali@example.com")

        with self.assertRaises(frappe.PermissionError):
            self.targets()

        self.assertEqual(self.reader.calls, [])
        self.has_permission.assert_not_called()
        self.assertEqual(frappe.local.message_log, [])

    def test_a_missing_document_is_not_found_and_nobody_is_listed(self):
        with self.assertRaises(frappe.DoesNotExistError):
            approvals_extra.forward_targets("Sales Invoice", "SINV-404")

        self.assertEqual(self.reader.calls, [])

    def test_a_blank_type_or_name_is_refused_before_anything_is_read(self):
        for doctype, name in (("", "SINV-1"), ("Sales Invoice", ""), ("  ", "  ")):
            with self.subTest(doctype=doctype, name=name):
                with self.assertRaises(frappe.ValidationError):
                    approvals_extra.forward_targets(doctype, name)
        self.get_doc.assert_not_called()
        self.assertEqual(self.reader.calls, [])

    def test_nothing_is_listed_without_pm(self):
        self.available.return_value = False
        self.candidates = people("ali@example.com")

        self.assertEqual(self.targets(), [])

        self.get_doc.assert_not_called()
        self.assertEqual(self.reader.calls, [])
        self.assertEqual(self.pm.method_calls, [])


# ─── forward and return_to_originator ─────────────────────────────────────────


class ActionCase(ExtraCase):
    """WA-1 is an action on a Sales Invoice (the one read the code makes of it
    is its document type, to refuse a hidden one)."""

    def setUp(self):
        super().setUp()
        self.action_doctypes = {"WA-1": "Sales Invoice"}
        frappe.local.db.get_value.side_effect = self._db_value
        self.pm.forward_workflow_action.return_value = {"adhoc_action": "WA-9", "return_to_originator": 1}
        self.pm.return_adhoc_to_originator.return_value = None

    def _db_value(self, doctype, name, fieldname, *args, **kwargs):
        if (doctype, fieldname) == (PM_ACTION, "reference_doctype"):
            return self.action_doctypes.get(name)
        raise AssertionError(f"unexpected db.get_value({doctype!r}, {name!r}, {fieldname!r})")

    def assert_pm_not_asked(self):
        self.pm.forward_workflow_action.assert_not_called()
        self.pm.return_adhoc_to_originator.assert_not_called()


class TestForward(ActionCase):
    def test_return_to_originator_reaches_pm_as_an_int(self):
        for given, expected in ((1, 1), ("1", 1), (True, 1), (0, 0), ("0", 0), ("", 0), (None, 0), ("abc", 0)):
            with self.subTest(given=given):
                self.pm.forward_workflow_action.reset_mock()

                approvals_extra.forward("WA-1", OMAR, "please check", given)

                self.pm.forward_workflow_action.assert_called_once_with("WA-1", OMAR, "please check", expected)
                (args, _kwargs) = self.pm.forward_workflow_action.call_args
                self.assertIs(type(args[3]), int)

    def test_the_defaults_are_no_comment_and_not_returned_to_the_originator(self):
        approvals_extra.forward("WA-1", OMAR)

        self.pm.forward_workflow_action.assert_called_once_with("WA-1", OMAR, "", 0)

    def test_pms_answer_is_returned_unchanged(self):
        self.pm.forward_workflow_action.return_value = {"adhoc_action": "WA-7", "return_to_originator": 0}

        self.assertEqual(
            approvals_extra.forward("WA-1", OMAR),
            {"adhoc_action": "WA-7", "return_to_originator": 0},
        )

    def test_the_target_is_trimmed_and_the_comment_is_text(self):
        approvals_extra.forward("WA-1", f"  {OMAR} ", None, 0)

        self.pm.forward_workflow_action.assert_called_once_with("WA-1", OMAR, "", 0)

    def test_a_blank_target_is_refused_before_pm(self):
        for blank in ("", "   ", None):
            with self.subTest(blank=blank):
                with self.assertRaises(frappe.ValidationError):
                    approvals_extra.forward("WA-1", blank)
        self.assert_pm_not_asked()

    def test_a_blank_action_is_refused_before_anything_is_read(self):
        for blank in ("", "  ", None):
            with self.subTest(blank=blank):
                with self.assertRaises(frappe.ValidationError):
                    approvals_extra.forward(blank, OMAR)
        self.assert_pm_not_asked()
        frappe.local.db.get_value.assert_not_called()

    def test_an_unknown_action_is_not_found(self):
        with self.assertRaises(frappe.DoesNotExistError):
            approvals_extra.forward("WA-404", OMAR)

        self.assert_pm_not_asked()

    def test_an_action_on_stock_entry_is_refused_before_pm(self):
        self.action_doctypes["WA-1"] = "Stock Entry"

        with self.assertRaises(frappe.PermissionError):
            approvals_extra.forward("WA-1", OMAR)

        self.assert_pm_not_asked()
        self.assertEqual(frappe.local.message_log, [])
        self.assertEqual(self.reader.calls, [])

    def test_an_action_on_a_type_pm_hides_is_refused_before_pm(self):
        self.pm.hidden_doctypes.return_value = ["Sales Invoice"]

        with self.assertRaises(frappe.PermissionError):
            approvals_extra.forward("WA-1", OMAR)

        self.assert_pm_not_asked()
        self.assertEqual(frappe.local.message_log, [])

    def test_pms_refusal_is_raised_unchanged(self):
        refusal = frappe.PermissionError("You can only forward actions assigned to you.")
        self.pm.forward_workflow_action.side_effect = refusal

        with self.assertRaises(frappe.PermissionError) as raised:
            approvals_extra.forward("WA-1", OMAR)

        self.assertIs(raised.exception, refusal)

    def test_without_pm_it_says_so_and_asks_nobody(self):
        self.available.return_value = False

        with self.assertRaises(frappe.ValidationError) as raised:
            approvals_extra.forward("WA-1", OMAR)

        self.assertIn("Approvals are not available on this site", str(raised.exception))
        self.assert_pm_not_asked()
        frappe.local.db.get_value.assert_not_called()


class TestReturnToOriginator(ActionCase):
    def test_the_action_and_comment_go_to_pm(self):
        approvals_extra.return_to_originator("WA-1", "looks fine to me")

        self.pm.return_adhoc_to_originator.assert_called_once_with("WA-1", "looks fine to me")

    def test_the_comment_defaults_to_nothing(self):
        approvals_extra.return_to_originator("WA-1")

        self.pm.return_adhoc_to_originator.assert_called_once_with("WA-1", "")

    def test_it_answers_ok_when_pm_answers_nothing(self):
        self.assertEqual(approvals_extra.return_to_originator("WA-1"), {"ok": True})

    def test_it_adds_what_pm_answers_when_pm_answers_a_dict(self):
        self.pm.return_adhoc_to_originator.return_value = {"original_action": "WA-0"}

        self.assertEqual(
            approvals_extra.return_to_originator("WA-1"), {"ok": True, "original_action": "WA-0"}
        )

    def test_a_blank_action_is_refused_before_anything_is_read(self):
        for blank in ("", "  ", None):
            with self.subTest(blank=blank):
                with self.assertRaises(frappe.ValidationError):
                    approvals_extra.return_to_originator(blank)
        self.assert_pm_not_asked()
        frappe.local.db.get_value.assert_not_called()

    def test_an_unknown_action_is_not_found(self):
        with self.assertRaises(frappe.DoesNotExistError):
            approvals_extra.return_to_originator("WA-404")

        self.assert_pm_not_asked()

    def test_a_hidden_type_is_refused_before_pm(self):
        for hidden in ("Stock Entry", "Gate Pass"):
            with self.subTest(hidden=hidden):
                self.action_doctypes["WA-1"] = hidden
                self.pm.hidden_doctypes.return_value = ["Gate Pass"]

                with self.assertRaises(frappe.PermissionError):
                    approvals_extra.return_to_originator("WA-1")

                self.assert_pm_not_asked()
                self.assertEqual(frappe.local.message_log, [])

    def test_pms_refusal_is_raised_unchanged(self):
        refusal = frappe.ValidationError("This is not an ad-hoc action.")
        self.pm.return_adhoc_to_originator.side_effect = refusal

        with self.assertRaises(frappe.ValidationError) as raised:
            approvals_extra.return_to_originator("WA-1")

        self.assertIs(raised.exception, refusal)

    def test_without_pm_it_says_so_and_asks_nobody(self):
        self.available.return_value = False

        with self.assertRaises(frappe.ValidationError):
            approvals_extra.return_to_originator("WA-1")

        self.assert_pm_not_asked()


# ─── attach ───────────────────────────────────────────────────────────────────


class FakeFile:
    """The File document `file_upload.upload` builds: what it was made from, and
    what the real `File` would set when saved."""

    def __init__(self, values: dict):
        self.values = values
        self.insert_kwargs = None
        self.file_name = values["file_name"]
        self.is_private = values["is_private"]
        self.file_url = ("/private/files/" if self.is_private else "/files/") + self.file_name

    def insert(self, **kwargs):
        self.insert_kwargs = kwargs
        return self


def action_row(name: str, docname: str = "SINV-1", doctype: str = "Sales Invoice", **overrides) -> dict:
    row = {
        "name": name,
        "reference_doctype": doctype,
        "reference_name": docname,
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


class AttachCase(ExtraCase):
    """sara holds the open action WA-1 on SINV-1 and may read it; the upload is
    a stub that stores nothing (`stub_upload = False` runs the real one)."""

    stub_upload = True

    def setUp(self):
        super().setUp()
        self.actions = [action_row("WA-1")]
        self.reader.handlers[PM_ACTION] = self._actions_of
        self.can_act = {"WA-1"}
        self.pm.can_act_on.side_effect = lambda action_doc, user: (
            user == ME and action_doc.name in self.can_act
        )
        self.readable = True
        self.has_permission = self._patch(
            "frappe.has_permission", side_effect=lambda *args, **kwargs: self.readable
        )
        self.files: list[FakeFile] = []
        self.get_doc = self._patch("frappe.get_doc", side_effect=self._get_doc)
        self.stored_names = {"/private/files/scan.pdf": "FILE-0001"}
        self.file_lookups: list = []
        frappe.local.db.get_value.side_effect = self._db_value
        self.upload = None
        if self.stub_upload:
            self.upload = self._patch(
                "vansale.api.file_upload.upload",
                return_value={"file_url": "/private/files/scan.pdf", "file_name": "scan.pdf", "is_private": 1},
            )

    def _actions_of(self, kwargs):
        filters = kwargs["filters"]
        return [
            row
            for row in self.actions
            if row["reference_doctype"] == filters["reference_doctype"]
            and row["reference_name"] == filters["reference_name"]
        ]

    def _get_doc(self, first, name=None, *args, **kwargs):
        if isinstance(first, dict):
            self.assertEqual(first["doctype"], "File")
            file = FakeFile(first)
            self.files.append(file)
            return file
        if first == PM_ACTION:
            return types.SimpleNamespace(doctype=first, name=name)
        raise AssertionError(f"unexpected get_doc({first!r}, {name!r})")

    def _db_value(self, doctype, filters, fieldname, *args, **kwargs):
        if doctype == "File" and fieldname == "name":
            self.file_lookups.append((filters, kwargs))
            return self.stored_names.get(filters["file_url"])
        raise AssertionError(f"unexpected db.get_value({doctype!r}, {filters!r}, {fieldname!r})")

    def attach(self, doctype="Sales Invoice", name="SINV-1", filename="scan.pdf", content="QUJD"):
        return approvals_extra.attach(doctype, name, filename, content)


class TestAttach(AttachCase):
    def test_a_caller_with_no_action_on_the_document_is_refused_before_any_file_exists(self):
        self.actions = []

        with self.assertRaises(frappe.PermissionError):
            self.attach()

        self.upload.assert_not_called()
        self.assertEqual(self.files, [])

    def test_a_caller_who_may_not_act_on_the_open_action_is_refused(self):
        self.can_act = set()

        with self.assertRaises(frappe.PermissionError):
            self.attach()

        self.upload.assert_not_called()

    def test_a_completed_action_is_no_reason_to_attach(self):
        self.actions = [action_row("WA-1", status="Completed"), action_row("WA-2", status="Forwarded")]
        self.can_act = {"WA-1", "WA-2"}

        with self.assertRaises(frappe.PermissionError):
            self.attach()

        self.upload.assert_not_called()

    def test_an_action_on_another_document_does_not_count(self):
        self.actions = [action_row("WA-1", docname="SINV-2")]

        with self.assertRaises(frappe.PermissionError):
            self.attach()

        self.upload.assert_not_called()

    def test_the_read_goes_to_the_documents_actions_only(self):
        self.attach()

        (kwargs,) = self.reader.of(PM_ACTION)
        self.assertEqual(kwargs["filters"], {"reference_doctype": "Sales Invoice", "reference_name": "SINV-1"})

    def test_a_caller_who_can_act_stores_a_private_file_on_the_document_and_gets_its_name_and_url(self):
        result = self.attach(filename="scan.pdf", content="QUJD")

        self.assertEqual(result, {"name": "FILE-0001", "url": "/private/files/scan.pdf"})
        self.upload.assert_called_once_with(
            "scan.pdf", "QUJD", attach_to_doctype="Sales Invoice", attach_to_name="SINV-1", is_private=1
        )
        # the File's own name is looked up from what the upload made, newest first
        (lookup,) = self.file_lookups
        self.assertEqual(
            lookup[0],
            {
                "file_url": "/private/files/scan.pdf",
                "attached_to_doctype": "Sales Invoice",
                "attached_to_name": "SINV-1",
            },
        )
        self.assertEqual(lookup[1], {"order_by": "creation desc"})

    def test_the_caller_must_be_able_to_read_the_document_too(self):
        self.readable = False

        with self.assertRaises(frappe.PermissionError):
            self.attach()

        self.has_permission.assert_called_once_with("Sales Invoice", "read", doc="SINV-1")
        self.upload.assert_not_called()

    def test_a_file_that_cannot_be_found_afterwards_is_an_error_not_a_made_up_name(self):
        self.stored_names = {}

        with self.assertRaises(frappe.ValidationError):
            self.attach()

    def test_stock_entry_is_refused_before_anything_is_read(self):
        with self.assertRaises(frappe.PermissionError):
            self.attach("Stock Entry", "STE-1")

        self.assert_nothing_happened()
        self.upload.assert_not_called()
        self.has_permission.assert_not_called()
        self.assertEqual(self.pm.method_calls, [])

    def test_a_type_pm_hides_is_refused_before_anything_is_read(self):
        self.pm.hidden_doctypes.return_value = ["Sales Invoice"]

        with self.assertRaises(frappe.PermissionError):
            self.attach()

        self.assert_nothing_happened()
        self.upload.assert_not_called()
        self.has_permission.assert_not_called()

    def test_a_blank_type_or_name_is_refused_before_anything_is_read(self):
        for doctype, name in (("", "SINV-1"), ("Sales Invoice", ""), (None, None)):
            with self.subTest(doctype=doctype, name=name):
                with self.assertRaises(frappe.ValidationError):
                    self.attach(doctype, name)
        self.assertEqual(self.reader.calls, [])
        self.upload.assert_not_called()

    def test_without_pm_it_says_so_and_stores_nothing(self):
        self.available.return_value = False

        with self.assertRaises(frappe.ValidationError) as raised:
            self.attach()

        self.assertIn("Approvals are not available on this site", str(raised.exception))
        self.assertEqual(self.reader.calls, [])
        self.upload.assert_not_called()


class TestAttachUsesTheExistingUpload(AttachCase):
    """The real `file_upload.upload` (it decodes and cleans the name) with the
    File document stubbed: the endpoint adds the permission check, not a copy of it."""

    stub_upload = False

    def setUp(self):
        super().setUp()
        self.stored_names = {"/private/files/my_scan.pdf": "FILE-0007"}

    def test_the_file_is_private_attached_to_the_document_and_cleaned(self):
        result = self.attach(filename="my scan.pdf", content="QUJD")  # "ABC"

        self.assertEqual(result, {"name": "FILE-0007", "url": "/private/files/my_scan.pdf"})
        (file,) = self.files
        self.assertEqual(file.values["file_name"], "my_scan.pdf")
        self.assertEqual(file.values["is_private"], 1)
        self.assertEqual(file.values["attached_to_doctype"], "Sales Invoice")
        self.assertEqual(file.values["attached_to_name"], "SINV-1")
        self.assertEqual(file.values["content"], b"ABC")
        # the user's own permissions apply to the File as to any upload
        self.assertEqual(file.insert_kwargs, {"ignore_permissions": False})

    def test_a_payload_that_is_not_base64_is_refused_and_nothing_is_stored(self):
        with self.assertRaises(frappe.ValidationError):
            self.attach(content="not base64 !!")

        self.assertEqual(self.files, [])
        self.assertEqual(self.file_lookups, [])

    def test_an_empty_payload_is_refused_and_nothing_is_stored(self):
        with self.assertRaises(frappe.ValidationError):
            self.attach(content="")

        self.assertEqual(self.files, [])


# ─── my_requests ──────────────────────────────────────────────────────────────


def request_row(name: str, doctype: str = "Sales Invoice", docname: str = "SINV-1", **overrides) -> dict:
    """One PM Workflow Action of a document the user submitted, as the read
    returns it."""
    row = {
        "name": name,
        "reference_doctype": doctype,
        "reference_name": docname,
        "workflow_state": "Pending Finance",
        "priority": "High",
        "assigned_to": None,
        "status": "Open",
        "creation": datetime(2026, 11, 10, 9, 30),
    }
    row.update(overrides)
    return row


class RequestsCase(ExtraCase):
    """Today is 19 Nov 2026. Every read answers from the lists below, and only
    for what it was asked about (names in the filter), so a wrong filter shows."""

    def setUp(self):
        super().setUp()
        self._patch("vansale.steelforce.approvals_extra.nowdate", return_value="2026-11-19")
        self.actions: list[dict] = []
        self.adhoc: list[dict] = []
        self.role_rows: list[dict] = []
        self.people = [
            {"name": ME, "full_name": "Sara Khan"},
            {"name": OMAR, "full_name": "Omar Saleh"},
            {"name": FATIMA, "full_name": "Fatima Noor"},
        ]
        self.documents: dict[str, list[dict]] = {
            "Sales Invoice": [{"name": f"SINV-{n}", "docstatus": 1} for n in range(1, 7)],
            "Purchase Invoice": [{"name": f"PINV-{n}", "docstatus": 1} for n in range(1, 4)],
            "Payment Entry": [{"name": "PE-1", "docstatus": 1}],
        }
        self.reader.handlers[PM_ACTION] = self._action_read
        self.reader.handlers[PM_ROLE] = lambda kwargs: [
            row for row in self.role_rows if row["parent"] in kwargs["filters"]["parent"][1]
        ]
        self.reader.handlers["User"] = lambda kwargs: [
            row for row in self.people if row["name"] in kwargs["filters"]["name"][1]
        ]
        for doctype in self.documents:
            self.reader.handlers[doctype] = self._document_read(doctype)

    def _action_read(self, kwargs):
        filters = kwargs["filters"]
        if "for_submitter" in filters:
            return list(self.actions)
        if filters.get("is_adhoc") == 1:
            return list(self.adhoc)
        raise AssertionError(f"unexpected PM Workflow Action read {kwargs}")

    def _document_read(self, doctype):
        return lambda kwargs: [
            row for row in self.documents[doctype] if row["name"] in kwargs["filters"]["name"][1]
        ]

    def requests(self) -> list[dict]:
        return approvals_extra.my_requests()["items"]


class TestMyRequests(RequestsCase):
    def test_one_row_per_document_the_oldest_wait_and_stock_entry_left_out(self):
        # newest first on purpose: the choice must not depend on the read's order
        self.actions = [
            request_row("WA-3", workflow_state="Pending GM", creation=datetime(2026, 11, 15, 8, 0)),
            request_row("WA-2", workflow_state="Pending Finance", creation=datetime(2026, 11, 10, 9, 30)),
            request_row("WA-1", doctype="Stock Entry", docname="STE-1", creation=datetime(2026, 11, 1, 9, 0)),
        ]

        items = self.requests()

        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]["doctype"], items[0]["docname"]), ("Sales Invoice", "SINV-1"))
        self.assertEqual(items[0]["state"], "Pending Finance")
        self.assertEqual(items[0]["days"], 9)
        # nothing was even read about the Stock Entry
        self.assertEqual(self.reader.count("Stock Entry"), 0)

    def test_each_row_has_the_contract_fields(self):
        self.actions = [request_row("WA-1", assigned_to=OMAR, priority="Critical")]
        self.role_rows = [{"parent": "WA-1", "approver": "Finance Head"}]

        self.assertEqual(
            self.requests(),
            [
                {
                    "doctype": "Sales Invoice",
                    "docname": "SINV-1",
                    "transaction": "Sales Invoice",
                    "state": "Pending Finance",
                    "holder": "Omar Saleh",
                    "role_id": "Finance Head",
                    "days": 9,
                    "priority": "Critical",
                }
            ],
        )

    def test_the_transaction_is_the_translated_document_type(self):
        self.actions = [request_row("WA-1")]
        self._patch("vansale.steelforce.approvals_extra._", side_effect=lambda text: f"ar:{text}")

        self.assertEqual(self.requests()[0]["transaction"], "ar:Sales Invoice")

    def test_the_read_is_the_signed_in_users_own_open_and_forwarded_actions(self):
        self.requests()

        (kwargs,) = self.reader.of(PM_ACTION)
        self.assertEqual(kwargs["filters"], {"for_submitter": ME, "status": ["in", ["Open", "Forwarded"]]})
        self.assertEqual(kwargs["order_by"], "creation asc")

    def test_another_user_gets_their_own_scope(self):
        frappe.local.session.user = OMAR

        self.requests()

        self.assertEqual(self.reader.of(PM_ACTION)[0]["filters"]["for_submitter"], OMAR)

    def test_a_type_pm_hides_is_left_out_without_being_read(self):
        self.pm.hidden_doctypes.return_value = ["Payment Entry"]
        self.actions = [
            request_row("WA-1"),
            request_row("WA-2", doctype="Payment Entry", docname="PE-1"),
        ]

        items = self.requests()

        self.assertEqual([item["docname"] for item in items], ["SINV-1"])
        self.assertEqual(self.reader.count("Payment Entry"), 0)

    def test_the_role_is_the_first_permitted_role_else_direct_for_a_named_user_else_blank(self):
        self.actions = [
            request_row("WA-A", docname="SINV-1", assigned_to=OMAR),
            request_row("WA-B", docname="SINV-2"),
            request_row("WA-C", docname="SINV-3"),
            request_row("WA-D", docname="SINV-4", assigned_to=OMAR),
        ]
        self.role_rows = [
            {"parent": "WA-B", "approver": "Finance Head"},
            {"parent": "WA-B", "approver": "Accounts Head"},
            {"parent": "WA-D", "approver": "General Manager"},
        ]

        by_doc = {item["docname"]: item for item in self.requests()}

        self.assertEqual(
            {doc: (item["role_id"], item["holder"]) for doc, item in by_doc.items()},
            {
                "SINV-1": ("Direct", "Omar Saleh"),
                "SINV-2": ("Finance Head", ""),
                "SINV-3": ("", ""),
                "SINV-4": ("General Manager", "Omar Saleh"),
            },
        )
        (roles,) = self.reader.of(PM_ROLE)
        self.assertEqual(
            roles["filters"],
            {
                "parent": ["in", ["WA-A", "WA-B", "WA-C", "WA-D"]],
                "parenttype": PM_ACTION,
                "approver_type": "Role",
            },
        )
        self.assertEqual(roles["order_by"], "idx asc")

    def test_a_holder_who_has_no_full_name_shows_the_user_id(self):
        self.people = [{"name": OMAR, "full_name": None}]
        self.actions = [request_row("WA-1", assigned_to=OMAR)]

        self.assertEqual(self.requests()[0]["holder"], OMAR)

    def test_a_forwarded_request_names_whoever_holds_it_now(self):
        self.actions = [
            request_row("WA-1", status="Forwarded", assigned_to=ME),
        ]
        self.role_rows = [{"parent": "WA-1", "approver": "Finance Head"}]
        # newest first: the document was forwarded on from Omar to Fatima
        self.adhoc = [
            {"reference_doctype": "Sales Invoice", "reference_name": "SINV-1", "assigned_to": FATIMA},
            {"reference_doctype": "Sales Invoice", "reference_name": "SINV-1", "assigned_to": OMAR},
            # same name, another type: not this document
            {"reference_doctype": "Purchase Invoice", "reference_name": "SINV-1", "assigned_to": ME},
        ]

        (item,) = self.requests()

        self.assertEqual(item["holder"], "Fatima Noor")
        self.assertEqual(item["role_id"], "Finance Head")
        self.assertEqual(item["state"], "Pending Finance")
        (adhoc,) = [k for k in self.reader.of(PM_ACTION) if "for_submitter" not in k["filters"]]
        self.assertEqual(
            adhoc["filters"], {"is_adhoc": 1, "status": "Open", "reference_name": ["in", ["SINV-1"]]}
        )
        self.assertEqual(adhoc["order_by"], "creation desc")

    def test_a_forwarded_request_with_no_open_ad_hoc_action_has_no_holder(self):
        self.actions = [request_row("WA-1", status="Forwarded", assigned_to=OMAR)]
        self.adhoc = []

        self.assertEqual(self.requests()[0]["holder"], "")

    def test_the_ad_hoc_read_is_made_only_when_something_is_forwarded(self):
        self.actions = [request_row("WA-1", assigned_to=OMAR)]

        self.requests()

        self.assertEqual(self.reader.count(PM_ACTION), 1)

    def test_a_cancelled_or_deleted_document_drops_out(self):
        self.documents["Sales Invoice"] = [
            {"name": "SINV-1", "docstatus": 1},
            {"name": "SINV-2", "docstatus": 2},
            {"name": "SINV-4", "docstatus": 0},
            # SINV-3 is gone
        ]
        self.actions = [
            request_row("WA-1", docname="SINV-1"),
            request_row("WA-2", docname="SINV-2"),
            request_row("WA-3", docname="SINV-3"),
            request_row("WA-4", docname="SINV-4"),
        ]

        items = self.requests()

        self.assertEqual(sorted(item["docname"] for item in items), ["SINV-1", "SINV-4"])
        (check,) = self.reader.of("Sales Invoice")
        self.assertEqual(check["filters"], {"name": ["in", ["SINV-1", "SINV-2", "SINV-3", "SINV-4"]]})
        self.assertEqual(check["fields"], ["name", "docstatus"])

    def test_a_read_that_fails_keeps_that_types_rows_and_defers_the_log(self):
        self.actions = [
            request_row("WA-1", docname="SINV-1"),
            request_row("WA-2", doctype="Purchase Invoice", docname="PINV-1"),
        ]

        def broken(kwargs):
            raise pymysql.err.OperationalError(1054, "Unknown column 'docstatus'")

        self.reader.handlers["Sales Invoice"] = broken
        log_error = self._patch("frappe.log_error")

        items = self.requests()

        self.assertEqual(sorted(item["docname"] for item in items), ["PINV-1", "SINV-1"])
        log_error.assert_called_once()
        self.assertTrue(log_error.call_args.kwargs["defer_insert"])
        self.assertIn("Sales Invoice", log_error.call_args.kwargs["title"])

    def test_a_type_that_no_longer_exists_keeps_its_rows(self):
        self.actions = [request_row("WA-1")]

        def gone(kwargs):
            raise frappe.DoesNotExistError("DocType Sales Invoice not found")

        self.reader.handlers["Sales Invoice"] = gone
        self._patch("frappe.log_error")

        self.assertEqual([item["docname"] for item in self.requests()], ["SINV-1"])

    def test_an_error_that_is_not_a_database_error_is_not_swallowed(self):
        self.actions = [request_row("WA-1")]

        def bug(kwargs):
            raise ValueError("a bug, not a bad table")

        self.reader.handlers["Sales Invoice"] = bug
        log_error = self._patch("frappe.log_error")

        with self.assertRaises(ValueError):
            self.requests()
        log_error.assert_not_called()

    def test_the_longest_waiting_come_first_and_ties_keep_the_order_they_came(self):
        self.actions = [
            request_row("WA-1", docname="SINV-1", creation=datetime(2026, 11, 17, 9, 0)),
            request_row("WA-2", docname="SINV-2", creation=datetime(2026, 11, 1, 9, 0)),
            request_row("WA-3", docname="SINV-3", creation=datetime(2026, 11, 17, 18, 0)),
            request_row("WA-4", docname="SINV-4", creation=datetime(2026, 11, 9, 9, 0)),
        ]

        items = self.requests()

        self.assertEqual([item["docname"] for item in items], ["SINV-2", "SINV-4", "SINV-1", "SINV-3"])
        self.assertEqual([item["days"] for item in items], [18, 10, 2, 2])

    def test_a_clock_ahead_of_the_site_gives_zero_days_not_a_negative_wait(self):
        self.actions = [request_row("WA-1", creation=datetime(2026, 11, 25, 9, 0))]

        self.assertEqual(self.requests()[0]["days"], 0)

    def test_a_blank_priority_is_medium(self):
        self.actions = [request_row("WA-1", priority=None)]

        self.assertEqual(self.requests()[0]["priority"], "Medium")

    def test_the_reads_are_bulk_never_per_row(self):
        self.actions = [
            request_row("WA-1", docname="SINV-1", assigned_to=OMAR),
            request_row("WA-2", docname="SINV-2", assigned_to=FATIMA),
            request_row("WA-3", docname="SINV-3", status="Forwarded"),
            request_row("WA-4", docname="SINV-4"),
            request_row("WA-5", doctype="Purchase Invoice", docname="PINV-1"),
            request_row("WA-6", doctype="Purchase Invoice", docname="PINV-2", assigned_to=OMAR),
        ]
        self.adhoc = [{"reference_doctype": "Sales Invoice", "reference_name": "SINV-3", "assigned_to": FATIMA}]

        self.assertEqual(len(self.requests()), 6)

        self.assertEqual(
            Counter(doctype for doctype, _kwargs in self.reader.calls),
            Counter(
                {
                    PM_ACTION: 2,  # the user's actions, then the ad-hoc holders
                    PM_ROLE: 1,
                    "User": 1,
                    "Sales Invoice": 1,
                    "Purchase Invoice": 1,
                }
            ),
        )

    def test_the_full_names_are_asked_for_only_the_people_shown(self):
        self.actions = [request_row("WA-1", assigned_to=OMAR)]

        self.requests()

        (kwargs,) = self.reader.of("User")
        self.assertEqual(kwargs["filters"], {"name": ["in", [OMAR]]})

    def test_no_actions_means_no_further_reads(self):
        self.assertEqual(approvals_extra.my_requests(), {"items": []})

        self.assertEqual(self.reader.count(PM_ACTION), 1)
        self.assertEqual(len(self.reader.calls), 1)

    def test_nothing_without_pm(self):
        self.available.return_value = False

        self.assertEqual(approvals_extra.my_requests(), {"items": []})

        self.assertEqual(self.reader.calls, [])
        self.assertEqual(self.pm.method_calls, [])

    def test_the_get_leaves_no_message_behind(self):
        self.actions = [request_row("WA-1", assigned_to=OMAR)]

        self.requests()

        self.assertEqual(frappe.local.message_log, [])


# ─── sent_back and history ────────────────────────────────────────────────────


def sent_back_row(docname: str, doctype: str = "Sales Invoice", **overrides) -> dict:
    row = {
        "doctype": doctype,
        "transaction": doctype,
        "transaction_filter": doctype,
        "docname": docname,
        "state": "Rejected",
        "submitted_by": "Sara Khan",
        "days": 3,
        "doc_url": f"/app/sales-invoice/{docname}",
        "sent_back_by": "Omar Saleh",
        "sent_back_on": datetime(2026, 11, 16, 9, 30, 45, 123456),
        "role": "Finance Head",
        "reason": "Wrong customer",
    }
    row.update(overrides)
    return row


def history_row(docname: str, doctype: str = "Sales Invoice", **overrides) -> dict:
    row = {
        "name": f"WA-{docname}",
        "doctype": doctype,
        "transaction": doctype,
        "transaction_filter": doctype,
        "docname": docname,
        "action_state": "Pending Finance",
        "current_state": "Approved",
        "role": "Finance Head",
        "completed_by": "Sara Khan",
        "date": "16/11/26 09:30",
        "doc_url": f"/app/sales-invoice/{docname}",
        "event_count": 2,
    }
    row.update(overrides)
    return row


class TestSentBack(ExtraCase):
    def setUp(self):
        super().setUp()
        self._patch("vansale.api.datetime_util.get_system_timezone", return_value="Asia/Kolkata")
        self.pm.get_sent_back_documents.return_value = [sent_back_row("SINV-1")]

    def test_pms_rows_come_back_with_the_time_as_a_utc_iso_string_to_the_second(self):
        (row,) = approvals_extra.sent_back()["items"]

        # 09:30:45.123456 in Asia/Kolkata (+05:30) is 04:00:45 UTC
        self.assertEqual(row["sent_back_on"], "2026-11-16T04:00:45Z")
        self.assertEqual(row, {**sent_back_row("SINV-1"), "sent_back_on": "2026-11-16T04:00:45Z"})

    def test_pms_own_rows_are_not_changed(self):
        rows = [sent_back_row("SINV-1")]
        self.pm.get_sent_back_documents.return_value = rows

        approvals_extra.sent_back()

        self.assertIsInstance(rows[0]["sent_back_on"], datetime)

    def test_a_row_without_a_time_is_left_alone(self):
        self.pm.get_sent_back_documents.return_value = [sent_back_row("SINV-1", sent_back_on=None)]

        self.assertIsNone(approvals_extra.sent_back()["items"][0]["sent_back_on"])

    def test_it_asks_pm_for_the_users_own_documents_only(self):
        approvals_extra.sent_back()

        self.pm.get_sent_back_documents.assert_called_once_with()

    def test_no_documents_is_an_empty_list(self):
        self.pm.get_sent_back_documents.return_value = None

        self.assertEqual(approvals_extra.sent_back(), {"items": []})

    def test_a_hidden_type_never_shows_even_if_pm_returned_it(self):
        self.pm.hidden_doctypes.return_value = ["Gate Pass"]
        self.pm.get_sent_back_documents.return_value = [
            sent_back_row("SINV-1"),
            sent_back_row("STE-1", doctype="Stock Entry"),
            sent_back_row("GP-1", doctype="Gate Pass"),
        ]

        self.assertEqual(
            [row["docname"] for row in approvals_extra.sent_back()["items"]], ["SINV-1"]
        )

    def test_nothing_without_pm(self):
        self.available.return_value = False

        self.assertEqual(approvals_extra.sent_back(), {"items": []})

        self.assertEqual(self.pm.method_calls, [])


class TestHistory(ExtraCase):
    def setUp(self):
        super().setUp()
        self.pm.get_my_approval_history.return_value = [history_row("SINV-1"), history_row("SINV-2")]

    def test_the_defaults_ask_pm_for_a_hundred_with_no_filters_and_never_everybodys(self):
        approvals_extra.history()

        self.pm.get_my_approval_history.assert_called_once_with(
            limit=100, from_date=None, to_date=None, transaction=None
        )

    def test_pms_rows_come_back_unchanged(self):
        rows = [history_row("SINV-1"), history_row("SINV-2", submitted_by="Ali")]
        self.pm.get_my_approval_history.return_value = rows

        self.assertEqual(approvals_extra.history()["items"], rows)

    def test_the_limit_is_a_number_between_one_and_two_hundred(self):
        cases = (
            ("50", 50), (50, 50), (500, 200), ("201", 200), (200, 200),
            (0, 1), (-5, 1), ("abc", 1), (None, 1), (1, 1),
        )  # fmt: skip
        for given, expected in cases:
            with self.subTest(given=given):
                self.pm.get_my_approval_history.reset_mock()

                approvals_extra.history(limit=given)

                limit = self.pm.get_my_approval_history.call_args.kwargs["limit"]
                self.assertEqual(limit, expected)
                self.assertIs(type(limit), int)

    def test_dates_and_transaction_are_passed_through_and_blank_means_none(self):
        approvals_extra.history(100, " 2026-11-01 ", "2026-11-19", "Sales Return")
        approvals_extra.history(100, "", "  ", "")

        self.assertEqual(
            self.pm.get_my_approval_history.call_args_list,
            [
                call(limit=100, from_date="2026-11-01", to_date="2026-11-19", transaction="Sales Return"),
                call(limit=100, from_date=None, to_date=None, transaction=None),
            ],
        )

    def test_everybodys_history_is_never_asked_for(self):
        approvals_extra.history(100, "2026-11-01", "2026-11-19", "Sales Return")

        self.assertNotIn("all_users", self.pm.get_my_approval_history.call_args.kwargs)

    def test_no_history_is_an_empty_list(self):
        self.pm.get_my_approval_history.return_value = None

        self.assertEqual(approvals_extra.history(), {"items": []})

    def test_a_hidden_type_never_shows_even_if_pm_returned_it(self):
        # PM's own-history read does not leave these out itself
        self.pm.hidden_doctypes.return_value = ["Gate Pass"]
        self.pm.get_my_approval_history.return_value = [
            history_row("SINV-1"),
            history_row("STE-1", doctype="Stock Entry"),
            history_row("GP-1", doctype="Gate Pass"),
            history_row("SINV-2"),
        ]

        self.assertEqual(
            [row["docname"] for row in approvals_extra.history()["items"]], ["SINV-1", "SINV-2"]
        )

    def test_nothing_without_pm(self):
        self.available.return_value = False

        self.assertEqual(approvals_extra.history(), {"items": []})

        self.assertEqual(self.pm.method_calls, [])


if __name__ == "__main__":
    unittest.main()
