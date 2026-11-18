"""Approvals for the app: the user's inbox of documents waiting on them, the
review of one document and the decision on it, backed by Permission Manager
(PM).

PM owns who may approve what; every call that decides something goes to PM
(`_pm()`), and this module only reshapes PM's answer for the phone. Nothing
here runs unless `permission_manager` is installed on the site: every endpoint
then answers "nothing here" instead of failing, and no PM function is called.

Items PM hides from the desk's own inbox (Stock Entry and any workflow flagged
`hide_from_approval_inbox`) never reach this module, so they never show.
"""

from __future__ import annotations

from html import unescape
from types import SimpleNamespace
from typing import Optional
from urllib.parse import quote

import frappe
from erpnext.accounts.utils import get_currency_precision
from frappe import _
from frappe.utils import cint, cstr, flt, get_datetime, now_datetime, strip_html

from vansale.api.datetime_util import naive_site_to_utc_iso
from vansale.steelforce.approvals_rules import area_of, check_apply, inbox_stats, tone_of
from vansale.steelforce.approvals_summary import first_lines, key_facts, pick_party_amount

PM_APP = "permission_manager"
PM_ACTION = "PM Workflow Action"
PM_TRANSITION = "PM Workflow Transition"

HIDDEN_DOCTYPES = ("Stock Entry",)
"""Never handled here, as PM keeps them out of its own inbox (with every type
PM's `_hidden_doctypes()` names: any with a workflow, active or not, flagged
`hide_from_approval_inbox`)."""

PRIORITIES = ("Low", "Medium", "High", "Critical")
BULK_LIMIT = 20
"""The most documents one bulk decision may cover."""
COMMENT_LIMIT = 20
"""The most workflow comments the detail shows, newest first."""

_ACTION_FIELDS = [
    "name", "status", "priority", "workflow_state", "assigned_to", "for_submitter",
    "completed_by", "is_adhoc", "adhoc_for", "return_to_originator",
]  # fmt: skip
_TRANSITION_FIELDS = [
    "action", "next_state", "require_comment", "require_attachment",
    "is_return_for_correction", "priority",
]  # fmt: skip
_REQUIREMENT_FLAGS = ("require_comment", "require_attachment", "is_return_for_correction")

_CURRENCY_FIELDS = ("currency", "paid_from_account_currency")
"""Where a document keeps the currency of its amount, best first (a Payment
Entry's `paid_amount` is in the paid-from account's currency)."""


def is_available() -> bool:
    """Permission Manager is installed on this site and has its action table."""
    return PM_APP in frappe.get_installed_apps() and bool(frappe.db.table_exists(PM_ACTION))


def _pm() -> SimpleNamespace:
    """The PM functions this module calls, imported on first use so the module
    loads on a site without PM. Every PM call goes through here; tests replace
    this one function."""
    from permission_manager.permission_manager import workflow as pm_workflow
    from permission_manager.permission_manager.api import approvals as pm_approvals
    from permission_manager.permission_manager.doctype.pm_workflow_action import (
        pm_workflow_action as pm_actions,
    )

    return SimpleNamespace(
        get_workflow=pm_workflow.get_workflow,
        hidden_doctypes=pm_approvals._hidden_doctypes,
        transaction_label=pm_approvals.transaction_label,
        get_my_pending_approvals=pm_approvals.get_my_pending_approvals,
        get_transitions=pm_workflow.get_transitions,
        apply_workflow=pm_workflow.apply_workflow,
        has_approval_access=pm_workflow.has_approval_access,
        get_open_return_adhoc_action=pm_workflow.get_open_return_adhoc_action,
        get_document_lifecycle=pm_approvals.get_document_lifecycle,
        forward_workflow_action=pm_actions.forward_workflow_action,
        return_adhoc_to_originator=pm_actions.return_adhoc_to_originator,
        get_sent_back_documents=pm_approvals.get_sent_back_documents,
        get_my_approval_history=pm_approvals.get_my_approval_history,
        can_act_on=pm_actions._can_act_on,
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────


@frappe.whitelist(methods=["GET"])
def availability() -> dict:
    """Whether approvals are available on this site (Permission Manager is
    installed): `{"enabled": bool}`."""
    return {"enabled": is_available()}


@frappe.whitelist(methods=["GET"])
def inbox() -> dict:
    """The signed-in user's approval inbox, as Permission Manager lists it.

    `sections` holds the documents waiting on the user, grouped by category;
    `waiting_items` holds the ones forwarded away or held by someone else (no
    buttons). `total` is PM's own total, so it matches the desk; `needs_you`
    is `total - waiting`. `stats` counts High/Critical and over-30-day items
    among the ones that need the user. Each item carries its party, amount and
    currency (one read per document type, made with the user's own read
    permissions, so a document they may not read shows without them), the
    person who forwarded it to the user, and the actions available in its
    state with what each one requires. Empty when Permission Manager is not
    installed."""
    if not is_available():
        return _empty_inbox()

    total, needs_you, waiting = _read_pending()
    pending = needs_you + waiting
    facts = _party_amounts(pending)
    flags = _action_flags(pending)
    forwarded = _forwarded_by(pending)

    def build(item: dict) -> dict:
        return _approval_item(item, facts, flags, forwarded)

    needs_you_items = [build(item) for item in needs_you]
    sections: list[dict] = []
    section_of: dict[str, dict] = {}
    for item in needs_you_items:
        section = section_of.get(item["category"])
        if section is None:
            section = section_of[item["category"]] = {"category": item["category"], "items": []}
            sections.append(section)
        section["items"].append(item)

    return {
        "total": total,
        "needs_you": max(total - len(waiting), 0),
        "waiting": len(waiting),
        "stats": inbox_stats(needs_you_items),
        "sections": sections,
        "waiting_items": [build(item) for item in waiting],
        "fetched_at": _now_iso(),
    }


@frappe.whitelist(methods=["GET"])
def count() -> dict:
    """The inbox numbers only, for badges: `total` (PM's own total, the same
    as the desk), `needs_you` (`total - waiting`), `waiting`, and `high` and
    `overdue` among the items that need the user. Zeros when Permission
    Manager is not installed."""
    if not is_available():
        return _empty_count()

    total, needs_you, waiting = _read_pending()
    return {
        "total": total,
        "needs_you": max(total - len(waiting), 0),
        "waiting": len(waiting),
        **inbox_stats(needs_you),
    }


@frappe.whitelist(methods=["GET"])
def detail(doctype: str, name: str) -> dict:
    """One document as the Approvals screen reviews it: header (state,
    priority, party, amount, creator), key facts, first lines, attachments,
    workflow comments, the route from Permission Manager's lifecycle, and the
    actions the signed-in user may take now, each with what it requires.

    Needs read permission on the document. A user who cannot read it but holds
    an open approval on it gets the bare record with `banner.kind ==
    "cannot_read"` and nothing of the document itself; anyone else is
    refused. Stock Entry and types whose workflow is hidden from the approval
    inbox are refused."""
    _require_available()
    doctype, name = cstr(doctype), cstr(name)
    user = frappe.session.user
    _refuse_if_hidden(doctype)

    if not frappe.has_permission(doctype, "read", doc=name):
        actions = _pm_actions(doctype, name)
        held = _held_action(actions, user)
        if not held:
            frappe.throw(
                _("You do not have permission to open {0} {1}").format(_(doctype), name),
                frappe.PermissionError,
            )
        return _unreadable_detail(doctype, name, held)

    return _readable_detail(frappe.get_doc(doctype, name), user)


@frappe.whitelist(methods=["POST"])
def apply(
    doctype: str,
    name: str,
    action: str,
    comment: str = "",
    priority: str = "",
    expected_state: str = "",
) -> dict:
    """Take `action` on one document as the signed-in user, through Permission
    Manager. The action must be one the document offers the user now, with the
    comment or attachment it requires. `expected_state` is the document's
    workflow state when the user opened it: when given and the document has
    moved since, it is refused before PM is asked. A blank `priority` leaves
    the transition's own priority; a chosen one is Low, Medium, High or
    Critical. Any refusal (PM's or the document's own) is raised unchanged.
    Returns `{"ok": True, "new_state", "recommended"}`; `recommended` is true
    when the user was asked for advice and the document did not move."""
    _require_available()
    return _apply_one(
        cstr(doctype),
        cstr(name),
        cstr(action),
        _comment(comment),
        _priority(priority),
        expected_state=cstr(expected_state),
    )


@frappe.whitelist(methods=["POST"])
def apply_bulk(
    doctype: str,
    names: str,
    action: str,
    comment: str = "",
    priority: str = "",
    expected_states: str = "",
) -> dict:
    """Take `action` on up to 20 documents of one type, one by one, with the
    same checks as `apply`. `names` is a JSON list (duplicates are dropped);
    `expected_states` is a JSON object `{docname: state when listed}`, and a
    document that moved since fails (a name not in it is not checked). A
    document on which the user was only asked for advice fails too: that is
    answered from its own screen. Each document is committed on success and
    rolled back on failure, and one failure never stops the others. Returns
    `{"results": [{"docname", "ok", "message"}], "ok_count", "failed_count"}`,
    where `message` is the refusal as plain text."""
    _require_available()
    doctype, action, comment = cstr(doctype), cstr(action), _comment(comment)
    priority = _priority(priority)
    docnames = _bulk_names(names)
    states = _expected_states(expected_states)
    _refuse_if_hidden(doctype)  # a hidden type refuses the whole batch

    results = []
    for docname in docnames:
        # A label an earlier document (or the request) left must not name this one.
        frappe.flags.pop("error_message", None)
        try:
            _apply_one(
                doctype,
                docname,
                action,
                comment,
                priority,
                expected_state=states.get(docname, ""),
                refuse_advice=True,
            )
            frappe.db.commit()
        except Exception as error:  # one document's trouble must not stop the batch
            message = _plain(_error_text(error))
            if not isinstance(error, (frappe.ValidationError, frappe.PermissionError)):
                # Not a refusal: something broke. Deferred, as the rollback
                # below would discard a row inserted now.
                frappe.log_error(title="vansale approvals: bulk apply", defer_insert=True)
            _rollback()
            results.append({"docname": docname, "ok": False, "message": message})
        else:
            results.append({"docname": docname, "ok": True, "message": ""})
        frappe.clear_messages()

    ok_count = sum(1 for result in results if result["ok"])
    return {"results": results, "ok_count": ok_count, "failed_count": len(results) - ok_count}


# ─── PM's inbox ───────────────────────────────────────────────────────────────


def _read_pending() -> tuple[int, list[dict], list[dict]]:
    """PM's pending approvals for the session user as `(total, needs_you,
    waiting)`: the items in PM's own order, split on `is_waiting`. An item
    without a category takes its group's label."""
    pending = _pm().get_my_pending_approvals() or {}
    items: list[dict] = []
    for group in pending.get("groups") or []:
        for item in group.get("items") or []:
            items.append({**item, "category": item.get("category") or group.get("label") or ""})

    needs_you = [item for item in items if not item.get("is_waiting")]
    waiting = [item for item in items if item.get("is_waiting")]
    return cint(pending.get("total", len(items))), needs_you, waiting


def _approval_item(item: dict, facts: dict, flags: dict, forwarded: dict) -> dict:
    """One ApprovalItem from a PM item and the three enrichment answers."""
    doctype = item.get("doctype") or ""
    docname = item.get("docname") or ""
    state = item.get("state") or ""
    fact = facts.get((doctype, docname)) or {}
    state_flags = flags.get((doctype, state)) or {}
    return {
        "action_id": item["name"],
        "doctype": doctype,
        "docname": docname,
        "transaction": item.get("transaction") or doctype,
        "area": area_of(doctype),
        "party": fact.get("party") or "",
        "amount": fact.get("amount"),
        "currency": fact.get("currency") or "",
        "priority": item.get("priority") or "Medium",
        "state": state,
        "role_id": item.get("role_id") or "",
        "days": cint(item.get("days")),
        "creator": item.get("creator") or "",
        "category": item.get("category") or "",
        "is_adhoc": bool(item.get("is_adhoc")),
        "forwarded_by": forwarded.get(item["name"], ""),
        "return_to_originator": bool(item.get("return_to_originator")),
        "is_waiting": bool(item.get("is_waiting")),
        "waiting_with": item.get("waiting_with") or "",
        "available_actions": [
            _action_flag(name, state_flags.get(name) or {})
            for name in item.get("available_actions") or []
        ],
    }


def _action_flag(action: str, flags: dict) -> dict:
    return {
        "action": action,
        "require_comment": bool(flags.get("require_comment")),
        "require_attachment": bool(flags.get("require_attachment")),
        "is_return_for_correction": bool(flags.get("is_return_for_correction")),
    }


def _empty_count() -> dict:
    return {"total": 0, "needs_you": 0, "waiting": 0, "high": 0, "overdue": 0}


def _empty_inbox() -> dict:
    return {
        "total": 0,
        "needs_you": 0,
        "waiting": 0,
        "stats": {"high": 0, "overdue": 0},
        "sections": [],
        "waiting_items": [],
        "fetched_at": _now_iso(),
    }


def _now_iso() -> str:
    """Now as a UTC ISO string (the app shows it in the phone's clock)."""
    return naive_site_to_utc_iso(now_datetime())


# ─── Enrichment: bulk reads, none per row ─────────────────────────────────────


def _party_amounts(items: list[dict]) -> dict[tuple[str, str], dict]:
    """`{(doctype, docname): {"party", "amount", "currency"}}` for the
    documents of PM items, with one `get_list` per document type, so the user
    sees only what their own permissions allow (roles, User Permissions,
    field-level permissions). A document that is not found or not readable by
    the user, a type the user may not read, or a type with no party or amount
    field is left out; a field the user may not read comes back as no value."""
    names_by_doctype: dict[str, list[str]] = {}
    for item in items:
        names_by_doctype.setdefault(item["doctype"], []).append(item["docname"])

    company_currency: dict[str, str] = {}
    facts: dict[tuple[str, str], dict] = {}
    for doctype, names in names_by_doctype.items():
        facts.update(_doctype_facts(doctype, list(dict.fromkeys(names)), company_currency))
    return facts


def _doctype_facts(doctype: str, names: list[str], company_currency: dict[str, str]) -> dict:
    try:
        meta = frappe.get_meta(doctype)
    except frappe.DoesNotExistError:
        return {}
    if not frappe.has_permission(doctype, "read"):
        # Not a type this user may read: nothing to show, and nothing to report.
        return {}

    party_field, amount_field = pick_party_amount(meta.has_field)
    if not (party_field or amount_field):
        return {}
    currency_field = next((f for f in _CURRENCY_FIELDS if meta.has_field(f)), None)
    company_field = "company" if meta.has_field("company") else None
    fields = ["name"] + [f for f in (party_field, amount_field, currency_field, company_field) if f]

    logged = len(frappe.local.message_log)
    try:
        rows = frappe.get_list(
            doctype, filters={"name": ["in", names]}, fields=fields, limit_page_length=0
        )
    except frappe.PermissionError:
        # Refused after all (a share that went away, say): the throw left a
        # message that would reach the user as a toast on this GET.
        if len(frappe.local.message_log) > logged:
            frappe.clear_last_message()
        return {}
    except _db_errors():
        # A bad field on one type must not hide the approvals themselves. The
        # row is deferred: this request is a GET, and its rollback would
        # discard an Error Log inserted now.
        frappe.log_error(title=f"vansale approvals: party and amount of {doctype}", defer_insert=True)
        return {}

    facts = {}
    for row in rows:
        amount = row.get(amount_field) if amount_field else None
        facts[(doctype, row.get("name"))] = {
            "party": cstr(row.get(party_field)) if party_field else "",
            # None, not 0, when the user may not read the amount field
            "amount": flt(amount) if amount is not None else None,
            "currency": _currency_of(row, currency_field, company_field, company_currency),
        }
    return facts


def _db_errors() -> tuple[type, ...]:
    """The database driver's error classes (looked up when an error is being
    handled, as they hang off the connected database)."""
    db = frappe.db
    return (db.ProgrammingError, db.OperationalError, db.InternalError, db.DataError)


def _currency_of(row, currency_field: Optional[str], company_field: Optional[str], memo: dict) -> str:
    """The document's own currency, else its company's currency, else ""."""
    if currency_field and row.get(currency_field):
        return cstr(row.get(currency_field))
    company = row.get(company_field) if company_field else None
    if not company:
        return ""
    if company not in memo:
        memo[company] = frappe.get_cached_value("Company", company, "default_currency") or ""
    return memo[company]


def _action_flags(items: list[dict]) -> dict[tuple[str, str], dict[str, dict]]:
    """`{(doctype, state): {action: flags}}` from the active PM workflows'
    transitions, one query for every item. Flags are `require_comment`,
    `require_attachment` and `is_return_for_correction`; an action that
    several approver roles share has a flag set if any of them sets it."""
    wanted = {
        (item["doctype"], item.get("state") or "")
        for item in items
        if item.get("available_actions")
    }
    if not wanted:
        return {}

    transition = frappe.qb.DocType("PM Workflow Transition")
    workflow = frappe.qb.DocType("PM Workflow")
    rows = (
        frappe.qb.from_(transition)
        .inner_join(workflow)
        .on(transition.parent == workflow.name)
        .select(
            workflow.document_type,
            transition.state,
            transition.action,
            transition.require_comment,
            transition.require_attachment,
            transition.is_return_for_correction,
        )
        .where(workflow.is_active == 1)
        .where(workflow.document_type.isin(sorted({doctype for doctype, _state in wanted})))
        .where(transition.state.isin(sorted({state for _doctype, state in wanted})))
    ).run(as_dict=True)

    flags: dict[tuple[str, str], dict[str, dict]] = {}
    for row in rows:
        key = (row.get("document_type"), row.get("state"))
        if key not in wanted:
            continue
        action = flags.setdefault(key, {}).setdefault(
            row.get("action"),
            {"require_comment": False, "require_attachment": False, "is_return_for_correction": False},
        )
        for flag in action:
            action[flag] = action[flag] or bool(cint(row.get(flag)))
    return flags


def _forwarded_by(items: list[dict]) -> dict[str, str]:
    """`{action id: full name}` of the user who forwarded each ad-hoc item to
    the session user: the `completed_by` of the original action it was
    forwarded for (`adhoc_for`). Two reads in all (the original actions, then
    their users), whatever the number of items."""
    originals = {
        item["name"]: item["adhoc_for"]
        for item in items
        if item.get("is_adhoc") and item.get("adhoc_for")
    }
    if not originals:
        return {}

    completed_by = {
        row.get("name"): row.get("completed_by")
        for row in frappe.get_all(
            PM_ACTION,
            filters={"name": ["in", list(dict.fromkeys(originals.values()))]},
            fields=["name", "completed_by"],
        )
        if row.get("completed_by")
    }
    if not completed_by:
        return {}

    full_names = {
        row.get("name"): row.get("full_name")
        for row in frappe.get_all(
            "User",
            filters={"name": ["in", list(dict.fromkeys(completed_by.values()))]},
            fields=["name", "full_name"],
        )
    }
    return {
        action_id: full_names.get(completed_by[original]) or completed_by[original]
        for action_id, original in originals.items()
        if original in completed_by
    }


# ─── Actions on one document ──────────────────────────────────────────────────


def _actions_for(doc, user: str, workflow=None) -> tuple[list[dict], Optional[str]]:
    """The actions `user` may take on `doc` now, as ActionSpecs, and the kind of
    banner that explains them: `"recommend"`, `"self_owned"` or None.

    A user holding an open "return to me" forward (PM answers which) is asked
    for advice: every transition of the state comes back `recommend_only`.
    Anyone else gets PM's transitions for them, less the ones PM's self-approval
    rule refuses; when that leaves nothing, the banner is `"self_owned"`.
    `workflow` is the document's PM Workflow when the caller has it."""
    pm = _pm()
    workflow = workflow or _workflow_of(doc)
    if not workflow:
        return [], None

    state = _state_of(doc, workflow)
    if pm.get_open_return_adhoc_action(doc, state, user):
        rows = frappe.get_all(
            PM_TRANSITION,
            filters={"parent": workflow.name, "state": state},
            fields=_TRANSITION_FIELDS,
            order_by="idx asc",
        )
        return _specs(rows, recommend_only=True), "recommend"

    transitions = pm.get_transitions(doc) or []
    allowed = [row for row in transitions if pm.has_approval_access(user, doc, row)]
    banner = "self_owned" if transitions and not allowed else None
    return _specs(allowed, recommend_only=False), banner


def _specs(rows: list, recommend_only: bool) -> list[dict]:
    """ActionSpecs from transition rows, one per action name in first-seen
    order; an action several approver rows share keeps a requirement if any of
    them sets it."""
    by_action: dict[str, dict] = {}
    for row in rows:
        action = cstr(row.get("action"))
        flags = {flag: bool(cint(row.get(flag))) for flag in _REQUIREMENT_FLAGS}
        spec = by_action.get(action)
        if spec is None:
            by_action[action] = {
                "action": action,
                "next_state": cstr(row.get("next_state")),
                **flags,
                "priority": row.get("priority") or "Medium",
                "recommend_only": recommend_only,
            }
        else:
            for flag, value in flags.items():
                spec[flag] = spec[flag] or value
    return [
        {**spec, "tone": tone_of(spec["action"], spec["is_return_for_correction"])}
        for spec in by_action.values()
    ]


def _apply_one(
    doctype: str,
    name: str,
    action: str,
    comment: str,
    priority: Optional[str],
    expected_state: str = "",
    refuse_advice: bool = False,
) -> dict:
    """`apply` for one document; `apply_bulk` runs every document through it.
    `comment` is already trimmed; `priority` None leaves the transition's own.
    `refuse_advice` refuses a document on which the user is only asked for
    advice (a batch would report advice as a decision)."""
    _refuse_if_hidden(doctype)
    doc = frappe.get_doc(doctype, name)
    # The read check PM's `get_transitions` makes; a "return to me" recipient's
    # recommendations do not go through `get_transitions`, so it is made here.
    # It comes before the state check, so the state is never told to someone
    # who may not read the document.
    doc.check_permission("read")
    workflow = _workflow_of(doc)
    if expected_state and expected_state != _state_of(doc, workflow):
        frappe.throw(_("This document changed since you opened it. Review it again."))
    specs, _banner = _actions_for(doc, frappe.session.user, workflow)
    spec = next((spec for spec in specs if spec["action"] == action), None)
    if refuse_advice and spec and spec["recommend_only"]:
        frappe.throw(_("Answer this one from its own screen"))

    refusal = check_apply(spec, comment, bool(spec) and bool(_attachments(doctype, name)))
    if refusal:
        frappe.throw(_refusal_text(refusal))

    _pm().apply_workflow(doc.as_dict(), action, comment or None, priority)
    return {
        "ok": True,
        "new_state": cstr(frappe.db.get_value(doctype, name, workflow.workflow_state_field)),
        "recommended": spec["recommend_only"],
    }


def _refusal_text(reason: str) -> str:
    if reason == "comment_required":
        return _("A comment is required for this action")
    if reason == "attachment_required":
        return _("Attach a file before this action")
    return _("This action is not available for this document")


def _priority(value) -> Optional[str]:
    """The chosen priority, or None when none was chosen (PM then uses the
    transition's own)."""
    priority = cstr(value).strip()
    if not priority:
        return None
    if priority not in PRIORITIES:
        frappe.throw(_("Priority must be Low, Medium, High or Critical"))
    return priority


def _comment(value) -> str:
    """The comment without surrounding spaces ("" for none)."""
    return cstr(value).strip()


def _expected_states(value) -> dict[str, str]:
    """`{docname: state}` from a bulk request's JSON object; {} when blank."""
    if isinstance(value, str):
        if not value.strip():
            return {}
        try:
            value = frappe.parse_json(value)
        except ValueError:
            value = None
    if not isinstance(value, dict):
        frappe.throw(_("Send the expected states as an object of document names"))
    return {cstr(name): cstr(state) for name, state in value.items()}


def _bulk_names(names) -> list[str]:
    """The document names of a bulk request, duplicates dropped, at most 20."""
    parsed = frappe.parse_json(names) if isinstance(names, str) else names
    if not isinstance(parsed, list):
        frappe.throw(_("Send the document names as a list"))
    docnames = list(dict.fromkeys(cstr(name) for name in parsed if cstr(name)))
    if len(docnames) > BULK_LIMIT:
        frappe.throw(_("At most {0} documents can be decided at once").format(BULK_LIMIT))
    return docnames


def _error_text(error: Exception) -> str:
    """What a failed document shows: the exception's own text, else the
    message Frappe set for a bare PermissionError, else a plain fallback."""
    text = cstr(error).strip() or cstr(frappe.flags.pop("error_message", None)).strip()
    return text or _("The action could not be applied")


def _plain(text: str) -> str:
    """A message as plain text: tags removed, entities decoded."""
    return unescape(strip_html(cstr(text))).strip()


def _rollback() -> None:
    """Roll back one bulk document; a rollback that fails (a lost connection,
    say) is logged and the batch goes on to report every document."""
    try:
        frappe.db.rollback()
    except Exception:
        frappe.log_error(title="vansale approvals: bulk rollback", defer_insert=True)


def _require_available() -> None:
    if not is_available():
        frappe.throw(_("Approvals are not available on this site"))


# ─── The detail record ────────────────────────────────────────────────────────


def _readable_detail(doc, user: str) -> dict:
    doctype, name = doc.doctype, doc.name
    pm = _pm()
    workflow = _workflow_of(doc)
    # Actions and labels are worked out on the whole document (PM's conditions
    # read it); the facts below show only the fields the user may read.
    actions, banner_kind = _actions_for(doc, user, workflow)
    state = _state_of(doc, workflow)
    transaction = pm.transaction_label(doctype, cint(doc.get("is_return")))

    pm_actions = _pm_actions(doctype, name)
    held = _held_action(pm_actions, user)
    holder = None if held else _waiting_holder(pm_actions, user)
    creator = (pm_actions[0].get("for_submitter") if pm_actions else None) or doc.owner
    comments = _workflow_comments(doctype, name)
    names = _full_names([creator, holder] + [c["user"] for c in comments if not c["by"]])

    if banner_kind == "recommend":
        forwarder = _forwarded_by([held]).get(held["name"], "") if held else ""
        banner = {"kind": "recommend", "forwarder": forwarder}
    elif holder:
        # Forwarded away: someone else holds it, so nothing is the user's to do.
        banner = {"kind": "waiting", "holder": names.get(holder) or holder}
        actions = []
    elif banner_kind == "self_owned":
        banner = {"kind": "self_owned"}
    else:
        banner = None

    doc.apply_fieldlevel_read_permissions()
    data = doc.as_dict()
    precision = get_currency_precision()
    fact = _doctype_facts(doctype, [name], {}).get((doctype, name)) or {}
    attachments = _attachments(doctype, name)

    return {
        **_blank_detail(doctype, name),
        "transaction": transaction,
        "state": state,
        "priority": _action_priority(held, pm_actions),
        "party": fact.get("party") or "",
        "amount": fact.get("amount"),
        "currency": fact.get("currency") or "",
        "creator": names.get(creator) or creator,
        "facts": key_facts(frappe.get_meta(doctype).fields, data, precision, translate=_),
        "lines": first_lines(doctype, data, precision, translate=_),
        "attachments": attachments,
        "has_attachment": bool(attachments),
        "comments": [
            {"by": c["by"] or names.get(c["user"]) or c["user"], "when": c["when"], "text": c["text"]}
            for c in comments
        ],
        "route": _route(doctype, name),
        "actions": actions,
        "action_id": held["name"] if held else None,
        "banner": banner,
        "can_forward": bool(held) and not (held.get("is_adhoc") and held.get("return_to_originator")),
    }


def _unreadable_detail(doctype: str, name: str, held: dict) -> dict:
    """The bare record for a user who holds an approval on a document they may
    not read: what the approval itself says, nothing of the document."""
    creator = held.get("for_submitter")
    names = _full_names([creator])
    return {
        **_blank_detail(doctype, name),
        "state": cstr(held.get("workflow_state")),
        "priority": held.get("priority") or "Medium",
        "creator": names.get(creator) or cstr(creator),
        "action_id": held["name"],
        "banner": {"kind": "cannot_read"},
    }


def _blank_detail(doctype: str, name: str) -> dict:
    """A Detail with every key present and nothing known."""
    return {
        "doctype": doctype,
        "docname": name,
        "transaction": doctype,
        "state": "",
        "priority": "Medium",
        "party": "",
        "amount": None,
        "currency": "",
        "creator": "",
        "facts": [],
        "lines": {"columns": [], "rows": [], "total": 0},
        "attachments": [],
        "has_attachment": False,
        "comments": [],
        "route": _route_of({}),
        "actions": [],
        "action_id": None,
        "banner": None,
        "can_forward": False,
        "desk_url": f"/app/{frappe.scrub(doctype).replace('_', '-')}/{quote(name, safe='')}",
    }


def _workflow_of(doc):
    """The PM Workflow that governs this document (PM picks it from the
    document's company, owner and dimensions), or None."""
    return _pm().get_workflow(doc.doctype, docname=doc.name, doc=doc, throw=False)


def _hidden_types() -> set[str]:
    """Stock Entry and every type PM hides from its approval inbox, lower-cased
    (the database finds a type whatever case it is written in)."""
    return {cstr(doctype).lower() for doctype in (*HIDDEN_DOCTYPES, *(_pm().hidden_doctypes() or []))}


def _is_hidden(doctype: str, hidden: Optional[set[str]] = None) -> bool:
    """Whether the approvals never handle this type, whatever its case.
    `hidden` is `_hidden_types()` when the caller has it; Stock Entry is
    refused without asking PM."""
    wanted = cstr(doctype).lower()
    if wanted in {always.lower() for always in HIDDEN_DOCTYPES}:
        return True
    return wanted in (_hidden_types() if hidden is None else hidden)


def _refuse_if_hidden(doctype: str) -> None:
    """Refuse a type the approvals never handle: Stock Entry, or a type PM
    hides from its inbox (decided per type, before any document is read)."""
    if _is_hidden(doctype):
        _refuse_hidden(doctype)


def _refuse_hidden(doctype: str) -> None:
    """Raise PermissionError the way Frappe's own permission checks do (no
    message queued for the response, the text in `flags.error_message`)."""
    message = _("{0} is not handled in Approvals").format(_(doctype))
    frappe.flags.error_message = message
    raise frappe.PermissionError(message)


def _state_of(doc, workflow) -> str:
    return cstr(doc.get(workflow.workflow_state_field)) if workflow else ""


def _route(doctype: str, name: str) -> dict:
    return _route_of(_pm().get_document_lifecycle(doctype, name) or {})


def _route_of(lifecycle: dict) -> dict:
    """PM's lifecycle with its five keys, the missing ones empty."""
    return {
        "chain": lifecycle.get("chain") or [],
        "roles": lifecycle.get("roles") or [],
        "events": lifecycle.get("events") or [],
        "current": cstr(lifecycle.get("current")),
        "finished": bool(lifecycle.get("finished")),
    }


def _pm_actions(doctype: str, name: str) -> list:
    """Every PM Workflow Action of the document, newest first."""
    return frappe.get_all(
        PM_ACTION,
        filters={"reference_doctype": doctype, "reference_name": name},
        fields=_ACTION_FIELDS,
        order_by="creation desc",
    )


def _can_act(action: dict, user: str) -> bool:
    return bool(_pm().can_act_on(frappe.get_doc(PM_ACTION, action["name"]), user))


def _held_action(actions: list, user: str) -> Optional[dict]:
    """The newest open action PM lets `user` act on, or None."""
    return next(
        (action for action in actions if action.get("status") == "Open" and _can_act(action, user)),
        None,
    )


def _waiting_holder(actions: list, user: str) -> Optional[str]:
    """Who holds the document when an action `user` could act on was forwarded
    to someone else: the assignee of the open ad-hoc action made for it."""
    for action in actions:
        if action.get("status") != "Forwarded" or not _can_act(action, user):
            continue
        for adhoc in actions:
            if (
                adhoc.get("status") == "Open"
                and adhoc.get("adhoc_for") == action["name"]
                and adhoc.get("assigned_to")
                and adhoc.get("assigned_to") != user
            ):
                return adhoc["assigned_to"]
    return None


def _action_priority(held: Optional[dict], actions: list) -> str:
    """The priority of the user's open action, else of any open action."""
    open_action = held or next((a for a in actions if a.get("status") == "Open"), None)
    return (open_action.get("priority") if open_action else None) or "Medium"


def _attachments(doctype: str, name: str) -> list[dict]:
    return [
        {"name": row.get("name"), "url": row.get("file_url"), "is_private": bool(cint(row.get("is_private")))}
        for row in frappe.get_all(
            "File",
            filters={"attached_to_doctype": doctype, "attached_to_name": name},
            fields=["name", "file_url", "is_private"],
            order_by="creation asc",
        )
    ]


def _workflow_comments(doctype: str, name: str) -> list[dict]:
    """The newest workflow comments as `{by, user, when, text}`; `by` is the
    name stored on the comment, `user` who wrote it."""
    rows = frappe.get_all(
        "Comment",
        filters={"reference_doctype": doctype, "reference_name": name, "comment_type": "Workflow"},
        fields=["owner", "comment_email", "comment_by", "content", "creation"],
        order_by="creation desc",
        limit=COMMENT_LIMIT,
    )
    return [
        {
            "by": cstr(row.get("comment_by")),
            "user": cstr(row.get("comment_email") or row.get("owner")),
            "when": get_datetime(row.get("creation")).strftime("%d/%m/%y %H:%M"),
            "text": unescape(strip_html(cstr(row.get("content")))).strip(),
        }
        for row in rows
    ]


def _full_names(users: list) -> dict[str, str]:
    """`{user: full name}` for the given users, in one read."""
    wanted = list(dict.fromkeys(user for user in users if user))
    if not wanted:
        return {}
    return {
        row.get("name"): row.get("full_name")
        for row in frappe.get_all("User", filters={"name": ["in", wanted]}, fields=["name", "full_name"])
        if row.get("full_name")
    }
