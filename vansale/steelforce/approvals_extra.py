"""Approvals, part two: forwarding an approval, attaching a file to the document
being decided, and the three lists beside the inbox (the user's own requests,
the documents sent back to them, and what they decided).

Like `approvals`, this is backed by Permission Manager (PM): every PM call goes
through `approvals._pm()` and the shared guards (`_refuse_if_hidden`,
`_workflow_of`, `_held_action`) are the ones the inbox endpoints use, so Stock
Entry and every type PM hides from its own inbox are refused or left out here
as they are there. Nothing here runs unless `permission_manager` is installed:
the reads then answer "nothing here" and the writes say approvals are not
available.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import frappe
from frappe import STANDARD_USERS, _
from frappe.utils import cint, cstr, date_diff, get_datetime, nowdate

from vansale.api import file_upload
from vansale.api.datetime_util import naive_site_to_utc_iso
from vansale.steelforce import approvals
from vansale.steelforce.approvals import PM_ACTION, PM_TRANSITION

PM_PERMITTED_ROLE = "PM Workflow Action Permitted Role"
"""The child table of a PM Workflow Action that lists who may act on it."""

TARGET_LIMIT = 20
"""The most people `forward_targets` offers."""
TARGET_BATCH = 100
"""How many candidates are read before the ones who may read the document are
kept: the cut to 20 comes after the read check, not before it."""
HISTORY_LIMIT = 200
"""The most documents `history` asks PM for."""

_REQUEST_FIELDS = [
    "name", "reference_doctype", "reference_name", "workflow_state", "priority",
    "assigned_to", "status", "creation",
]  # fmt: skip


# ─── Forward ──────────────────────────────────────────────────────────────────


@frappe.whitelist(methods=["GET"])
def forward_targets(doctype: str, name: str, query: str = "") -> list[dict]:
    """Up to 20 people the document can be forwarded to: enabled system users
    whose user id or full name contains `query`, left out unless they may read
    this document (a forward does not share it), and never the caller. Each is
    `{"user", "full_name", "role"}`; `role` is the person's first role that
    appears on the workflow's transitions for the document's current state, or
    "". The caller needs read permission on the document; Stock Entry and types
    PM hides from its inbox are refused. Empty when Permission Manager is not
    installed."""
    if not approvals.is_available():
        return []
    doctype, name, query = cstr(doctype).strip(), cstr(name).strip(), cstr(query).strip()
    _require_document(doctype, name)
    approvals._refuse_if_hidden(doctype)

    doc = frappe.get_doc(doctype, name)
    doc.check_permission("read")

    readable: list = []
    for candidate in _candidates(frappe.session.user, query):
        # Judged as the candidate, on the loaded document (a name would load it
        # again for each of the hundred).
        if frappe.has_permission(doctype, "read", doc=doc, user=candidate.get("name")):
            readable.append(candidate)
            if len(readable) == TARGET_LIMIT:
                break

    roles = _first_roles(doc, [candidate.get("name") for candidate in readable])
    return [
        {
            "user": candidate.get("name"),
            "full_name": candidate.get("full_name") or candidate.get("name"),
            "role": roles.get(candidate.get("name"), ""),
        }
        for candidate in readable
    ]


def _candidates(user: str, query: str) -> list:
    """Enabled system users matching `query`, without the caller and the
    standard users, by name. The users are listed with `get_all` on purpose: a
    desk user may only *pick* a User, never read the list, yet picking a
    colleague to forward to is the whole point; only the id and full name are
    read, as the desk's own user search does, and every name is then checked
    against the document before it is shown."""
    or_filters = (
        {"name": ["like", f"%{query}%"], "full_name": ["like", f"%{query}%"]} if query else None
    )
    return frappe.get_all(
        "User",
        filters={
            "enabled": 1,
            "user_type": "System User",
            "name": ["not in", [*STANDARD_USERS, user]],
        },
        or_filters=or_filters,
        fields=["name", "full_name"],
        order_by="full_name asc, name asc",
        limit=TARGET_BATCH,
    )


def _first_roles(doc, users: list[str]) -> dict[str, str]:
    """`{user: role}`: each user's first role that is on the transitions of the
    document's own workflow for its current state. Two reads at most, whatever
    the number of users; a user with no such role is left out."""
    if not users:
        return {}
    workflow = approvals._workflow_of(doc)
    state = approvals._state_of(doc, workflow)
    if not (workflow and state):
        return {}

    transition_roles = frappe.get_all(
        PM_TRANSITION,
        filters={"parent": workflow.name, "state": state, "approver_type": "Role"},
        fields=["allowed"],
        order_by="idx asc",
    )
    wanted = list(dict.fromkeys(row.get("allowed") for row in transition_roles if row.get("allowed")))
    if not wanted:
        return {}

    first: dict[str, str] = {}
    for row in frappe.get_all(
        "Has Role",
        filters={"parenttype": "User", "parent": ["in", users], "role": ["in", wanted]},
        fields=["parent", "role"],
        order_by="idx asc",
    ):
        first.setdefault(row.get("parent"), row.get("role"))
    return first


@frappe.whitelist(methods=["POST"])
def forward(action_id: str, to_user: str, comment: str = "", return_to_originator: int = 0) -> dict:
    """Forward the signed-in user's open approval `action_id` to `to_user`,
    through Permission Manager (which makes the other person's approval and
    does not share the document). The caller must hold the approval (PM lets
    them act on it and it is still open); otherwise, and for an approval on
    Stock Entry or a type PM hides, the answer is "Approval not found", the
    same as for an id that does not exist. `return_to_originator` asks the
    other person for advice only: the approval comes back to the caller.
    Returns PM's answer, `{"adhoc_action", "return_to_originator"}`.
    `to_user` must be an enabled system user other than the caller who may
    read the document, as the people offered by `forward_targets` are; anyone
    else is refused before PM is asked."""
    approvals._require_available()
    action_id, to_user, comment = cstr(action_id).strip(), cstr(to_user).strip(), cstr(comment)
    if not to_user:
        frappe.throw(_("Choose who to forward this to"))
    # The caller's own hold comes first: nothing about the recipient (who
    # exists, who may read the document) is told to someone who does not hold it.
    doctype, docname = _held_open_action(action_id)
    recipient = _forward_recipient(to_user, doctype, docname)
    return approvals._pm().forward_workflow_action(action_id, recipient, comment, cint(return_to_originator))


def _forward_recipient(to_user: str, doctype: str, docname: str) -> str:
    """The user id to forward the approval on `doctype` `docname` to, after the
    checks PM leaves out (it only checks that the user exists): an enabled
    system user (so not a website user, Guest or Administrator, none of whom
    the picker offers), not the caller, and one who may read the document, since
    a forward does not share it and someone who cannot read it could not act on
    it. The user id is the record's own, as the database matches an id without
    regard to case. The messages carry nothing the caller typed."""
    record = frappe.db.get_value("User", to_user, ["name", "enabled", "user_type"], as_dict=True)
    if (
        not record
        or not cint(record.get("enabled"))
        or record.get("user_type") != "System User"
        or record.get("name") in STANDARD_USERS
    ):
        frappe.throw(_("Choose an active system user to forward to"))

    user = record.get("name")
    if user == frappe.session.user:
        frappe.throw(_("You cannot forward an approval to yourself"))
    if not frappe.has_permission(doctype, "read", doc=docname, user=user):
        frappe.throw(_("That person cannot read this document, so it cannot be forwarded to them"))
    return user


@frappe.whitelist(methods=["POST"])
def return_to_originator(action_id: str, comment: str = "") -> dict:
    """Hand an approval that was forwarded "return to me" back to the person who
    asked, through Permission Manager (which also checks it is ad hoc). The
    caller must hold it open, as for `forward`; otherwise, and for Stock Entry
    or a type PM hides, the answer is "Approval not found". Returns
    `{"ok": True}` plus anything PM answers."""
    approvals._require_available()
    action_id, comment = cstr(action_id).strip(), cstr(comment)
    _held_open_action(action_id)
    answer = approvals._pm().return_adhoc_to_originator(action_id, comment)
    return {"ok": True, **(answer if isinstance(answer, dict) else {})}


def _held_open_action(action_id: str) -> tuple[str, str]:
    """The `(doctype, name)` of the document an approval is about, once the
    caller is known to hold it: it exists, names a document of a type the
    approvals handle, is still Open, and PM lets the caller act on it. Any
    other approval gets one answer, "Approval not found" as a PermissionError,
    so an id cannot be used to learn whether it exists, what it is about or
    who holds it. Checked before PM is asked anything."""
    if not action_id:
        frappe.throw(_("Choose an approval first"))
    action = frappe.db.get_value(
        PM_ACTION, action_id, ["reference_doctype", "reference_name", "status"], as_dict=True
    )
    if (
        not action
        or not action.get("reference_doctype")
        or not action.get("reference_name")
        or approvals._is_hidden(action.get("reference_doctype"))
        or action.get("status") != "Open"
        or not approvals._pm().can_act_on(frappe.get_doc(PM_ACTION, action_id), frappe.session.user)
    ):
        frappe.throw(_("Approval not found"), frappe.PermissionError)
    return action.get("reference_doctype"), action.get("reference_name")


# ─── Attach ───────────────────────────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
def attach(doctype: str, name: str, filename: str, content_base64: str) -> dict:
    """Attach a file (base64, no data-URL prefix) to a document the signed-in
    user has to act on, so an action that requires an attachment can follow.
    The caller must hold an open approval on the document they may act on (PM's
    rule) and may read it; anyone else, and Stock Entry and types PM hides, are
    refused before any file is made. The file is private; its name is cleaned
    and decoded by the app's own upload. Returns `{"name", "url"}` of the File."""
    approvals._require_available()
    doctype, name = cstr(doctype).strip(), cstr(name).strip()
    _require_document(doctype, name)
    approvals._refuse_if_hidden(doctype)

    held = approvals._held_action(approvals._pm_actions(doctype, name), frappe.session.user)
    if not (held and frappe.has_permission(doctype, "read", doc=name)):
        frappe.throw(_("You cannot attach files to this document"), frappe.PermissionError)

    saved = file_upload.upload(
        cstr(filename),
        cstr(content_base64),
        attach_to_doctype=doctype,
        attach_to_name=name,
        is_private=1,
    )
    url = saved["file_url"]
    # `upload` answers the file's url and name, not the File record's own name
    file_name = frappe.db.get_value(
        "File",
        {"file_url": url, "attached_to_doctype": doctype, "attached_to_name": name},
        "name",
        order_by="creation desc",
    )
    if not file_name:
        frappe.throw(_("The file could not be attached"))
    return {"name": file_name, "url": url}


# ─── The user's own requests ──────────────────────────────────────────────────


@frappe.whitelist(methods=["GET"])
def my_requests() -> dict:
    """The documents the signed-in user submitted that are still moving through
    approval: one row per document, longest waiting first, with where it is
    (`state`), who holds it (`holder`, a person's full name, for a forwarded
    approval the person it was forwarded to), the role it waits on (`role_id`,
    or "Direct" when it is assigned to a person), `days` waiting and
    `priority`. Documents that no longer exist or were cancelled, Stock Entry
    and types PM hides are left out. Empty when Permission Manager is not
    installed."""
    if not approvals.is_available():
        return {"items": []}

    hidden = approvals._hidden_types()
    # `get_all` is safe here: the read is scoped to the user's own submissions
    # (`for_submitter` is the signed-in user), so it never lists another
    # person's approvals; the documents themselves are not read, only their
    # existence below.
    rows = frappe.get_all(
        PM_ACTION,
        filters={"for_submitter": frappe.session.user, "status": ["in", ["Open", "Forwarded"]]},
        fields=_REQUEST_FIELDS,
        order_by="creation asc",
    )
    oldest: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row.get("reference_doctype"), row.get("reference_name"))
        if approvals._is_hidden(key[0], hidden):
            continue
        waiting = oldest.get(key)
        if waiting is None or get_datetime(row.get("creation")) < get_datetime(waiting.get("creation")):
            oldest[key] = row

    gone = _gone_documents(list(oldest))
    kept = [row for key, row in oldest.items() if key not in gone]
    if not kept:
        return {"items": []}

    roles = _permitted_roles([row.get("name") for row in kept])
    holders = _ad_hoc_holders(kept)
    holder_of = {
        row.get("name"): (
            holders.get((row.get("reference_doctype"), row.get("reference_name")))
            if row.get("status") == "Forwarded"
            else row.get("assigned_to")
        )
        for row in kept
    }
    names = approvals._full_names(list(holder_of.values()))

    today = nowdate()
    items = [
        {
            "doctype": row.get("reference_doctype"),
            "docname": row.get("reference_name"),
            "transaction": _(row.get("reference_doctype")),
            "state": cstr(row.get("workflow_state")),
            "holder": names.get(holder_of[row.get("name")]) or holder_of[row.get("name")] or "",
            "role_id": roles.get(row.get("name")) or ("Direct" if row.get("assigned_to") else ""),
            "days": max(date_diff(today, row.get("creation")), 0),
            "priority": row.get("priority") or "Medium",
        }
        for row in kept
    ]
    items.sort(key=lambda item: -item["days"])  # stable: ties keep their order
    return {"items": items}


def _gone_documents(keys: list[tuple[str, str]]) -> set[tuple[str, str]]:
    """The `(doctype, name)` keys whose document no longer exists or is
    cancelled, from one read per document type (name and docstatus only). A type
    whose read fails (removed, or a bad table) keeps all its rows: failing open,
    as PM does, and the error is logged for later (this request is a GET, so
    the row is deferred)."""
    names_by_doctype: dict[str, list[str]] = {}
    for doctype, name in keys:
        names_by_doctype.setdefault(doctype, []).append(name)

    gone: set[tuple[str, str]] = set()
    for doctype, names in names_by_doctype.items():
        try:
            rows = frappe.get_all(doctype, filters={"name": ["in", names]}, fields=["name", "docstatus"])
        except (frappe.DoesNotExistError, *approvals._db_errors()):
            frappe.log_error(
                title=f"vansale approvals: my requests, documents of {doctype}", defer_insert=True
            )
            continue
        alive = {row.get("name") for row in rows if cint(row.get("docstatus")) != 2}
        gone.update((doctype, name) for name in names if name not in alive)
    return gone


def _permitted_roles(action_names: list[str]) -> dict[str, str]:
    """`{action: first permitted Role}` in one read; an action that lists no
    Role is left out."""
    first: dict[str, str] = {}
    for row in frappe.get_all(
        PM_PERMITTED_ROLE,
        filters={"parent": ["in", action_names], "parenttype": PM_ACTION, "approver_type": "Role"},
        fields=["parent", "approver"],
        order_by="idx asc",
    ):
        first.setdefault(row.get("parent"), row.get("approver"))
    return first


def _ad_hoc_holders(rows: list[dict]) -> dict[tuple[str, str], str]:
    """`{(doctype, name): user}` who holds each forwarded document now: the
    assignee of the newest open ad-hoc approval on it (the newest, as a
    forward can be forwarded on). One read, and only when something is
    forwarded."""
    wanted = {
        (row.get("reference_doctype"), row.get("reference_name"))
        for row in rows
        if row.get("status") == "Forwarded"
    }
    if not wanted:
        return {}

    holders: dict[tuple[str, str], str] = {}
    for row in frappe.get_all(
        PM_ACTION,
        filters={
            "is_adhoc": 1,
            "status": "Open",
            "reference_name": ["in", sorted({docname for _doctype, docname in wanted})],
        },
        fields=["reference_doctype", "reference_name", "assigned_to"],
        order_by="creation desc",
    ):
        key = (row.get("reference_doctype"), row.get("reference_name"))
        if key in wanted and row.get("assigned_to"):
            holders.setdefault(key, row.get("assigned_to"))
    return holders


# ─── Sent back and history ────────────────────────────────────────────────────


@frappe.whitelist(methods=["GET"])
def sent_back() -> dict:
    """The documents an approver sent back to the signed-in user for
    correction, as Permission Manager lists them (who sent it back, when, the
    role and the reason). `sent_back_on` is a UTC ISO time to the second.
    Empty when Permission Manager is not installed."""
    if not approvals.is_available():
        return {"items": []}
    rows = approvals._pm().get_sent_back_documents() or []
    return {"items": [_with_iso_times(row) for row in _without_hidden(rows)]}


@frappe.whitelist(methods=["GET"])
def history(limit: int = 100, from_date: str = "", to_date: str = "", transaction: str = "") -> dict:
    """The decisions the signed-in user took (and what happened to documents
    they submitted), as Permission Manager lists them, newest first. `limit`
    counts documents, 1 to 200; `from_date` and `to_date` (YYYY-MM-DD) and
    `transaction` (PM's label, such as "Sales Return") narrow it, and a blank
    one does not. Never everybody's history. Empty when Permission Manager is
    not installed."""
    if not approvals.is_available():
        return {"items": []}
    rows = approvals._pm().get_my_approval_history(
        limit=min(max(cint(limit), 1), HISTORY_LIMIT),
        from_date=_text_or_none(from_date),
        to_date=_text_or_none(to_date),
        transaction=_text_or_none(transaction),
    ) or []
    return {"items": _without_hidden(rows)}


def _without_hidden(rows: list[dict]) -> list[dict]:
    """The rows whose document type the approvals handle. PM's own-history read
    does not leave Stock Entry or hidden types out the way its inbox does, so
    every row is checked here, whichever list it came from."""
    hidden = approvals._hidden_types()
    return [row for row in rows if not approvals._is_hidden(row.get("doctype"), hidden)]


def _with_iso_times(row: dict) -> dict:
    """A copy of the row with each datetime as a UTC ISO string to the second
    (PM hands the site's own clock; the app shows it in the phone's)."""
    return {
        key: naive_site_to_utc_iso(value.replace(microsecond=0)) if isinstance(value, datetime) else value
        for key, value in row.items()
    }


# ─── Shared ───────────────────────────────────────────────────────────────────


def _require_document(doctype: str, name: str) -> None:
    if not (doctype and name):
        frappe.throw(_("Document type and name are required"))


def _text_or_none(value) -> Optional[str]:
    return cstr(value).strip() or None
