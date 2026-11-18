"""The approvals parity report: a developer check that the Approvals lists in
the app show what `permission_manager` (PM) shows on the desk, for one user.

For the user it compares

- PM's own `get_my_pending_approvals` (the desk's "My Approvals") with
  `approvals.inbox()` and `approvals.count()`: the total, the number waiting on
  others, the "needs you" figure and the items in both lists;
- PM's own `get_sent_back_documents` with `approvals_extra.sent_back()`;
- an independent read of the user's requests (the open or forwarded PM Workflow
  Actions with `for_submitter` = the user, one per document, on documents that
  still exist and are not cancelled, Stock Entry and the types PM hides left
  out) with `approvals_extra.my_requests()`.

It is not an endpoint (nothing here is whitelisted): run it from a console,

    bench --site <site> execute vansale.steelforce.approvals_parity.parity_report \
        --kwargs "{'user': '<user>'}"

It reads and writes nothing, apart from the Error Log row an enrichment read
may defer when a document type's party or amount cannot be read. While it runs
the session is the given user's, so every figure is what that user would see,
and it is handed back to whoever ran the report whatever happens. Run it while
nothing is moving: the sources are read one after the other, so a document that
is decided in between shows as a difference.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Optional

import frappe
from frappe import _
from frappe.utils import cint, cstr

from vansale.steelforce import approvals, approvals_extra

REQUEST_STATUSES = ["Open", "Forwarded"]
"""The statuses of an approval that is still open (a forwarded one is open
with the person it was forwarded to)."""


def parity_report(user: str) -> dict:
    """The report for `user`: `{"user", "desk_total", "pwa_total",
    "desk_waiting", "pwa_waiting", "needs_you", "sent_back_equal",
    "my_requests_equal", "ok", "differences"}`.

    `needs_you` is the PWA's total less its waiting. `differences` lists every
    comparison that failed, so `ok` is true exactly when it is empty. A figure
    is `{"field", "desk", "pwa"}` (`field` is `total`, `waiting`, `needs_you`,
    or `count.` and one of those for the badge numbers); a list is `{"field",
    "only_desk", "only_pwa"}` (`field` is `sections` and `waiting_items`, which
    hold PM action ids, and `sent_back` and `my_requests`, which hold
    `[doctype, name]` pairs), naming what only one side has. For
    `my_requests` the "desk" side is the independent read.

    Refused for a user that does not exist, and on a site without Permission
    Manager (there is no desk to compare with, and an empty report would look
    like a pass)."""
    user = cstr(user).strip()
    if not user or not frappe.db.exists("User", user):
        frappe.throw(_("User {0} not found").format(user))
    if not approvals.is_available():
        frappe.throw(_("Approvals are not available on this site"))

    previous = frappe.session.user
    try:
        frappe.set_user(user)
        return _report(user)
    finally:
        frappe.set_user(previous)


def _report(user: str) -> dict:
    """Every comparison, made as the session user."""
    pm = approvals._pm()
    differences: list[dict] = []

    # The inbox and the badge.
    desk = pm.get_my_pending_approvals() or {}
    desk_items = [item for group in desk.get("groups") or [] for item in group.get("items") or []]
    desk_total = cint(desk.get("total", len(desk_items)))
    desk_waiting_ids = [item.get("name") for item in desk_items if item.get("is_waiting")]
    desk_needs_you_ids = [item.get("name") for item in desk_items if not item.get("is_waiting")]
    desk_waiting = len(desk_waiting_ids)
    wanted = {
        "total": desk_total,
        "waiting": desk_waiting,
        "needs_you": desk_total - desk_waiting,
    }

    inbox = approvals.inbox()
    count = approvals.count()
    for prefix, answer in (("", inbox), ("count.", count)):
        for key, value in wanted.items():
            if answer.get(key) != value:
                differences.append({"field": prefix + key, "desk": value, "pwa": answer.get(key)})

    pwa_total = cint(inbox.get("total"))
    pwa_waiting = cint(inbox.get("waiting"))
    for field, desk_ids, pwa_ids in (
        (
            "sections",
            desk_needs_you_ids,
            [
                item.get("action_id")
                for section in inbox.get("sections") or []
                for item in section.get("items") or []
            ],
        ),
        (
            "waiting_items",
            desk_waiting_ids,
            [item.get("action_id") for item in inbox.get("waiting_items") or []],
        ),
    ):
        _note(differences, _only_one_side(field, desk_ids, pwa_ids))

    # Sent back: the pairs, not the other columns or their order.
    sent_back = _only_one_side(
        "sent_back",
        _pairs(pm.get_sent_back_documents() or [], "doctype", "docname"),
        _pairs(approvals_extra.sent_back().get("items") or [], "doctype", "docname"),
    )
    _note(differences, sent_back)

    # My requests: against an independent read of the actions.
    my_requests = _only_one_side(
        "my_requests",
        _open_requests(user, pm),
        _pairs(approvals_extra.my_requests().get("items") or [], "doctype", "docname"),
    )
    _note(differences, my_requests)

    return {
        "user": user,
        "desk_total": desk_total,
        "pwa_total": pwa_total,
        "desk_waiting": desk_waiting,
        "pwa_waiting": pwa_waiting,
        "needs_you": pwa_total - pwa_waiting,
        "sent_back_equal": sent_back is None,
        "my_requests_equal": my_requests is None,
        "ok": not differences,
        "differences": differences,
    }


def _open_requests(user: str, pm) -> list[tuple[str, str]]:
    """The documents `user` submitted that are still with an approver, read from
    the PM Workflow Actions themselves: those with `for_submitter` = the user
    that are open or forwarded, once per document, less Stock Entry and the
    types PM hides, and less documents that were deleted or cancelled (PM's own
    inbox drops them the same way). One read of the actions, then one per
    document type."""
    hidden = {*approvals.HIDDEN_DOCTYPES, *(pm.hidden_doctypes() or [])}
    rows = frappe.get_all(
        approvals.PM_ACTION,
        filters={"for_submitter": user, "status": ["in", REQUEST_STATUSES]},
        fields=["reference_doctype", "reference_name"],
    )
    named: dict[str, list[str]] = {}
    for row in rows:
        doctype = row.get("reference_doctype")
        if doctype not in hidden:
            named.setdefault(doctype, []).append(row.get("reference_name"))

    requests: set[tuple[str, str]] = set()
    for doctype, names in named.items():
        alive = frappe.get_all(
            doctype,
            filters={"name": ["in", list(dict.fromkeys(names))], "docstatus": ["!=", 2]},
            pluck="name",
        )
        requests.update((doctype, name) for name in alive)
    return sorted(requests)


def _pairs(rows: Iterable[dict], doctype_key: str, name_key: str) -> list[tuple]:
    return [(row.get(doctype_key), row.get(name_key)) for row in rows]


def _only_one_side(field: str, desk: Iterable, pwa: Iterable) -> Optional[dict]:
    """None when both sides hold the same entries (order aside, a repeated
    entry counting each time), else what only the desk has and what only the
    PWA has."""
    desk_count, pwa_count = Counter(desk), Counter(pwa)
    only_desk = sorted((desk_count - pwa_count).elements(), key=repr)
    only_pwa = sorted((pwa_count - desk_count).elements(), key=repr)
    if not (only_desk or only_pwa):
        return None
    return {
        "field": field,
        "only_desk": [_plain(entry) for entry in only_desk],
        "only_pwa": [_plain(entry) for entry in only_pwa],
    }


def _plain(entry):
    """A pair as a list, so the report reads the same as JSON."""
    return list(entry) if isinstance(entry, tuple) else entry


def _note(differences: list[dict], difference: Optional[dict]) -> None:
    if difference:
        differences.append(difference)
