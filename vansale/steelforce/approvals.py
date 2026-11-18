"""Approvals for the app: the user's inbox of documents waiting on them, backed
by Permission Manager (PM).

PM owns who may approve what; every call that decides something goes to PM
(`_pm()`), and this module only reshapes PM's answer for the phone. Nothing
here runs unless `permission_manager` is installed on the site: every endpoint
then answers "nothing here" instead of failing, and no PM function is called.

Items PM hides from the desk's own inbox (Stock Entry and any workflow flagged
`hide_from_approval_inbox`) never reach this module, so they never show.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import frappe
from frappe.utils import cint, cstr, flt, now_datetime

from vansale.api.datetime_util import naive_site_to_utc_iso
from vansale.steelforce.approvals_rules import area_of, inbox_stats
from vansale.steelforce.approvals_summary import pick_party_amount

PM_APP = "permission_manager"
PM_ACTION = "PM Workflow Action"

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
