# apps/vansale/vansale/sf_trading/api/payment_advice_workflow.py
"""PM Workflow for Payment Advice — modelled on the live "Payment Request Approval".

permission_manager's PM Workflow is its own approval engine (there is no native Frappe
Workflow record behind it), driven by a `workflow_state` field on the target doctype. This
module creates the equivalent workflow for Payment Advice and tells the rest of sf_trading
whether it is active, because two behaviours have to step aside when it is:

  * `PaymentAdvice.validate_approver()` — the single-approver rule ("only the linked user may
    submit") would fight the workflow, where an Accountant approves documents raised by
    someone else. When a workflow is active the workflow's own permissions decide.
  * the payment automation — with an approval workflow in force, a scheduled run must not
    submit advices behind the approvers' backs. It stops at drafts and records why.

Creation is idempotent and non-destructive: an existing workflow is left exactly as it is
unless `force=1` is passed, so a workflow tuned on site is never overwritten by a deploy.

Shape — four routes out of Draft, decided by what the advice pays for and converging on the
same two final approvals:

    several Purchase Orders   Draft → Purchase Manager ┐
    any overdue invoice       Draft → HO Accounts      ├→ GM or Finance Manager → Bahrain Accountant → Approved
    invoices over BHD 500     Draft ───────────────────┘
    one PO, or BHD 500 or less  Draft ──────────────────────────────────────────────→ Bahrain Accountant → Approved

Branch Head and Purchase Assistant raise on every route, and must attach the paperwork when
they do — the payment slip or supporting statement belongs to whoever raises the advice, not to
an approver further up who has nothing new to attach. The GM and the Finance Manager are
interchangeable for the second approval — either one is enough. Only the Bahrain Accountant's
approval submits the document. Any pending state can be rejected with a comment, which returns
the advice to Draft for correction.

Which route an advice takes is decided in the Payment Advice controller and stored in its
`approval_route` field; the transitions out of Draft test that field and nothing else, because
PM Workflow runs conditions through frappe.safe_eval with almost no globals — a condition
cannot count child rows. Note that Administrator is exempt from condition checks in the engine,
so an advice with no stored route still looks fine when tested as Administrator and offers a
real preparer nothing at all: `migrate_open_advices` exists to stamp the route on advices saved
before the field existed.
"""

import frappe
from frappe import _
from frappe.utils import cint

WORKFLOW_NAME = "Payment Advice Approval"
DOCTYPE = "Payment Advice"

STATE_DRAFT = "Draft"
STATE_PENDING = "Pending Approval"          # retired — kept so old documents can be migrated
STATE_PENDING_PURCHASE = "Pending Purchase Manager"
STATE_PENDING_HO = "Pending HO Accounts"
STATE_PENDING_FINANCE = "Pending Finance"
STATE_PENDING_ACCOUNTANT = "Pending Accountant"
STATE_APPROVED = "Approved"
STATE_REJECTED = "Rejected"

# Who raises an advice
ROLE_BRANCH_HEAD = "Branch Head"
ROLE_PURCHASE_ASSISTANT = "Purchase Assistant"
# The Bahrain Accountant raises advices too, for both orders and invoices, so the role appears
# on both sides of the chain. Where that would leave an advice approved only by the person who
# raised it, payment_advice.set_approval_route() escalates it - see the note on the final
# transition below.
PREPARER_ROLES = (ROLE_BRANCH_HEAD, ROLE_PURCHASE_ASSISTANT, "Bahrain Accountant")

# Who signs it off
ROLE_PURCHASE_MANAGER = "Purchase Manager"
ROLE_HO_ACCOUNTS = "HO Accounts"
ROLE_GM = "General Manager"
ROLE_FINANCE_MANAGER = "Finance Manager"
FINANCE_ROLES = (ROLE_GM, ROLE_FINANCE_MANAGER)   # either may give the second approval
ROLE_APPROVER = "Bahrain Accountant"              # always the last pair of eyes

# Read from the controller so the figure exists in exactly one place. It is written into the
# transition conditions below, which is where anyone looking for "the BHD 500 rule" will look.
from vansale.sf_trading.doctype.payment_advice.payment_advice import FINANCE_APPROVAL_LIMIT

# The four routes, matching vansale.sf_trading.doctype.payment_advice.payment_advice.
# Each names the state an advice enters when it leaves Draft.
ROUTE_ENTRY_STATE = {
    "Accountant": STATE_PENDING_ACCOUNTANT,
    "Purchase Manager": STATE_PENDING_PURCHASE,
    "HO Accounts": STATE_PENDING_HO,
    "Finance": STATE_PENDING_FINANCE,
}

# Roles this workflow needs that are not part of a stock site. Everything else already
# exists on the live site; only the final approver had no role of its own.
ROLES_TO_CREATE = (ROLE_APPROVER,)


def pm_workflow_available():
    """Is permission_manager installed on this site?"""
    return bool(frappe.db.exists("DocType", "PM Workflow"))


def has_active_workflow(company=None):
    """True when a PM Workflow is live for Payment Advice.

    Callers use this to stand down their own approval logic. Cheap and cached per request,
    because it runs inside document validation.
    """
    if not pm_workflow_available():
        return False

    key = "sf_payment_advice_workflow_active_%s" % (company or "*")
    cached = frappe.local.cache.get(key) if hasattr(frappe.local, "cache") else None
    if cached is not None:
        return cached

    filters = {"document_type": DOCTYPE, "is_active": 1}
    if company:
        filters["company"] = ["in", [company, ""]]

    active = bool(frappe.db.exists("PM Workflow", filters))

    if hasattr(frappe.local, "cache"):
        frappe.local.cache[key] = active
    return active


def _default_email_alert():
    """Follow whatever the site's other PM Workflows do about approval email.

    Steel Force has these switched off while no outgoing Email Account exists — every
    transition would otherwise log "Failed to send workflow action email". A new workflow that
    ignored that would quietly start filling the Error Log again. With no workflows to learn
    from (a fresh site) email stays on, which is permission_manager's own default.
    """
    existing = frappe.get_all("PM Workflow", pluck="send_email_alert")
    if not existing:
        return 1
    return 1 if any(cint(v) for v in existing) else 0


def _states(company):
    """Every state the advice can sit in, and who may edit it there."""
    return [
        {"state": STATE_DRAFT, "doc_status": "0", "allow_edit": ROLE_BRANCH_HEAD},
        {"state": STATE_PENDING_PURCHASE, "doc_status": "0", "allow_edit": ROLE_PURCHASE_MANAGER},
        {"state": STATE_PENDING_HO, "doc_status": "0", "allow_edit": ROLE_HO_ACCOUNTS},
        {"state": STATE_PENDING_FINANCE, "doc_status": "0", "allow_edit": ROLE_FINANCE_MANAGER},
        {"state": STATE_PENDING_ACCOUNTANT, "doc_status": "0", "allow_edit": ROLE_APPROVER},
        {"state": STATE_APPROVED, "doc_status": "1", "allow_edit": ROLE_APPROVER},
        {"state": STATE_REJECTED, "doc_status": "0", "allow_edit": ROLE_BRANCH_HEAD},
    ]


def _transitions(company):
    """The four routes out of Draft, converging on Finance → Accountant.

        several POs      Draft → Purchase Manager ┐
        overdue invoice  Draft → HO Accounts      ├→ Finance (GM or Finance Manager) → Accountant → Approved
        over the limit   Draft ────────────────────┘
        one PO / small   Draft ──────────────────────────────────────────────────────→ Accountant → Approved

    Which one an advice takes is decided when it is saved and stored in `approval_route`;
    the conditions below only compare that string, because PM Workflow evaluates them through
    frappe.safe_eval with almost no globals — there is no counting rows from here.
    """
    transitions = []

    # The limit, written into the conditions rather than hidden in Python, so it can be read
    # and changed from the PM Workflow screen. `or 0` because an empty amount would otherwise
    # raise inside safe_eval and the transition would silently disappear.
    within_limit = "(doc.payment_amount or 0) <= %g" % FINANCE_APPROVAL_LIMIT
    over_limit = "(doc.payment_amount or 0) > %g" % FINANCE_APPROVAL_LIMIT

    # ── leaving Draft (and leaving Rejected after a correction) ────────────────────
    for route, entry_state in ROUTE_ENTRY_STATE.items():
        condition = 'doc.approval_route == "%s"' % route
        direct = entry_state == STATE_PENDING_ACCOUNTANT
        for from_state in (STATE_DRAFT, STATE_REJECTED):
            for role in PREPARER_ROLES:
                cond = condition
                # The accountant is the only approver on the direct route, so an advice they
                # raise there is one they would release alone. Within the limit that is the
                # delegation the limit grants. Over it, the row below sends it to Finance
                # instead, so somebody else approves before it reaches their own desk.
                if direct and role == ROLE_APPROVER:
                    cond = "%s and %s" % (condition, within_limit)
                transitions.append({
                    "state": from_state,
                    "action": "Send for Approval",
                    "next_state": entry_state,
                    "allowed": role,
                    "condition": cond,
                    # the paperwork belongs to whoever raises the advice — payment slip,
                    # supporting invoice, outstanding statement. An approver further up the
                    # chain has nothing to attach that the initiator did not already have.
                    "require_attachment": 1,
                    "allow_self_approval": 1,
                })

            if direct:
                transitions.append({
                    "state": from_state,
                    "action": "Send for Approval",
                    "next_state": STATE_PENDING_FINANCE,
                    "allowed": ROLE_APPROVER,
                    "condition": "%s and %s" % (condition, over_limit),
                    "require_attachment": 1,
                    "allow_self_approval": 1,
                })

    # ── first approval, per route ──────────────────────────────────────────────────
    transitions.append({
        "state": STATE_PENDING_PURCHASE,
        "action": "Approve",
        "next_state": STATE_PENDING_FINANCE,
        "allowed": ROLE_PURCHASE_MANAGER,
        "allow_self_approval": 0,
    })
    transitions.append({
        "state": STATE_PENDING_HO,
        "action": "Approve",
        "next_state": STATE_PENDING_FINANCE,
        "allowed": ROLE_HO_ACCOUNTS,
        "allow_self_approval": 0,
    })

    # ── second approval: either the GM or the Finance Manager, one is enough ───────
    for role in FINANCE_ROLES:
        transitions.append({
            "state": STATE_PENDING_FINANCE,
            "action": "Approve",
            "next_state": STATE_PENDING_ACCOUNTANT,
            "allowed": role,
            "allow_self_approval": 0,
        })

    # ── the last pair of eyes, and the only transition that submits ───────────────
    # Self-approval is permitted here, which needs saying out loud: this is the one state every
    # route ends at, and the Bahrain Accountant is its only approver, so refusing it would strand
    # every advice the accountant raised with nobody able to release it. It is safe because an
    # advice only reaches this state one of two ways - either it came through Purchase Manager,
    # HO Accounts or Finance, where somebody else already approved it, or it is within the
    # delegated limit and was never meant to need a second signature. The case that would
    # otherwise slip through - the accountant raising a large advice on the direct route and
    # releasing it alone - is closed upstream, by escalating it to Finance before it gets here.
    transitions.append({
        "state": STATE_PENDING_ACCOUNTANT,
        "action": "Approve",
        "next_state": STATE_APPROVED,
        "allowed": ROLE_APPROVER,
        "allow_self_approval": 1,
    })

    # ── rejection, available to whoever is holding it ─────────────────────────────
    rejecters = (
        (STATE_PENDING_PURCHASE, ROLE_PURCHASE_MANAGER),
        (STATE_PENDING_HO, ROLE_HO_ACCOUNTS),
        (STATE_PENDING_FINANCE, ROLE_GM),
        (STATE_PENDING_FINANCE, ROLE_FINANCE_MANAGER),
        (STATE_PENDING_ACCOUNTANT, ROLE_APPROVER),
    )
    for state, role in rejecters:
        transitions.append({
            "state": state,
            "action": "Reject",
            "next_state": STATE_REJECTED,
            "allowed": role,
            "require_comment": 1,
            "is_return_for_correction": 1,
            "allow_self_approval": 0,
        })

    return transitions


def ensure_workflow_masters():
    """Create the Workflow State / Workflow Action Master records the transitions link to.

    PM Workflow's `state` and `next_state` are Links into Frappe's own `Workflow State` table,
    and `action` into `Workflow Action Master`. Frappe validates those links on save, so a
    workflow naming a state that has no master record is rejected outright — which is exactly
    what happened the first time this workflow was rebuilt with the new states.
    """
    created = []

    styles = {
        STATE_DRAFT: "",
        STATE_PENDING_PURCHASE: "Warning",
        STATE_PENDING_HO: "Warning",
        STATE_PENDING_FINANCE: "Warning",
        STATE_PENDING_ACCOUNTANT: "Warning",
        STATE_APPROVED: "Success",
        STATE_REJECTED: "Danger",
    }
    for state, style in styles.items():
        if frappe.db.exists("Workflow State", state):
            continue
        frappe.get_doc({
            "doctype": "Workflow State",
            "workflow_state_name": state,
            "style": style,
        }).insert(ignore_permissions=True)
        created.append("Workflow State: %s" % state)

    for action in ("Send for Approval", "Approve", "Reject"):
        if frappe.db.exists("Workflow Action Master", action):
            continue
        frappe.get_doc({
            "doctype": "Workflow Action Master",
            "workflow_action_name": action,
        }).insert(ignore_permissions=True)
        created.append("Workflow Action Master: %s" % action)

    if created:
        frappe.db.commit()

    return created


def ensure_roles():
    """Create the roles this workflow needs that a stock site does not have.

    Only the final approver is new; Branch Head, Purchase Assistant, Purchase Manager,
    HO Accounts, General Manager and Finance Manager already exist on the live site. A role is
    created empty — who holds it is the client's decision, not a deploy's, and an advice
    cannot reach its last state until somebody is given it.
    """
    created = []
    for role in ROLES_TO_CREATE:
        if frappe.db.exists("Role", role):
            continue
        frappe.get_doc({
            "doctype": "Role",
            "role_name": role,
            "desk_access": 1,
        }).insert(ignore_permissions=True)
        created.append(role)

    if created:
        frappe.db.commit()

    return created


@frappe.whitelist()
def route_readiness():
    """Can every state of this workflow actually be reached? Who is missing?

    An approval chain with a role nobody holds strands documents in that state with no way
    forward, which is worse than no workflow at all — so this is worth checking before the
    workflow goes live and after any staff change.
    """
    from frappe.utils.user import get_users_with_role

    roles = list(PREPARER_ROLES) + [
        ROLE_PURCHASE_MANAGER, ROLE_HO_ACCOUNTS, ROLE_GM, ROLE_FINANCE_MANAGER, ROLE_APPROVER
    ]
    holders = {}
    for role in roles:
        holders[role] = get_users_with_role(role) if frappe.db.exists("Role", role) else []

    # the second approval needs only one of the two finance roles between them
    finance_cover = holders.get(ROLE_GM, []) + holders.get(ROLE_FINANCE_MANAGER, [])
    blocking = [role for role in roles if role not in FINANCE_ROLES and not holders[role]]
    if not finance_cover:
        blocking.append("%s / %s" % (ROLE_GM, ROLE_FINANCE_MANAGER))

    return {
        "ready": not blocking,
        "unstaffed_roles": blocking,
        "holders": {role: len(users) for role, users in holders.items()},
    }


@frappe.whitelist()
def setup_workflow(company: str = None, force: int = 0):
    """Create (or optionally rebuild) the Payment Advice PM Workflow.

    Idempotent: an existing workflow is reported and left untouched unless force=1.
    """
    frappe.only_for(("System Manager", "Accounts Manager"))

    if not pm_workflow_available():
        frappe.throw(
            _("permission_manager is not installed on this site, so PM Workflow cannot be created.")
        )

    company = company or frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
        "Global Defaults", "default_company"
    )
    if not company:
        frappe.throw(_("Company is required."))

    created_roles = ensure_roles()
    created_masters = ensure_workflow_masters()

    missing = [
        role
        for role in PREPARER_ROLES
        + (ROLE_PURCHASE_MANAGER, ROLE_HO_ACCOUNTS, ROLE_APPROVER)
        + FINANCE_ROLES
        if not frappe.db.exists("Role", role)
    ]
    if missing:
        frappe.throw(
            _("These roles do not exist on this site: %s") % frappe.bold(", ".join(missing))
        )

    existing = frappe.db.exists("PM Workflow", WORKFLOW_NAME)
    if existing and not cint(force):
        return {
            "created": False,
            "workflow": WORKFLOW_NAME,
            "message": _("%s already exists and was left untouched.") % WORKFLOW_NAME,
        }

    doc = frappe.get_doc("PM Workflow", WORKFLOW_NAME) if existing else frappe.new_doc("PM Workflow")
    doc.update(
        {
            "workflow_name": WORKFLOW_NAME,
            "document_type": DOCTYPE,
            "company": company,
            "is_active": 1,
            "send_email_alert": _default_email_alert(),
            "allow_descendants": 1,
            "workflow_state_field": "workflow_state",
            "reminder_after_days": 3,
            "escalate_after_days": 7,
        }
    )

    doc.set("states", [])
    for state in _states(company):
        state = dict(state)
        state.update({"company": company, "send_email": 1, "edit_permission_type": "Role"})
        doc.append("states", state)

    doc.set("transitions", [])
    for transition in _transitions(company):
        transition = dict(transition)
        transition.update(
            {
                "company": company,
                "approver_type": "Role",
                "priority": "Medium",
                # Payment Request Approval sets this on every transition; keep parity so the
                # approver-matrix engine treats both workflows the same way.
                "matrix_level": 1,
            }
        )
        doc.append("transitions", transition)

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "created": not bool(existing),
        "rebuilt": bool(existing and cint(force)),
        "workflow": doc.name,
        "roles_created": created_roles,
        "masters_created": created_masters,
        "readiness": route_readiness(),
        "states": [s.state for s in doc.states],
        "transitions": ["%s → %s (%s)" % (t.state, t.next_state, t.action) for t in doc.transitions],
        "message": _("%s is active. Payment Advice submission is now controlled by the workflow.")
        % doc.name,
    }


@frappe.whitelist()
def migrate_open_advices(dry_run: int = 1):
    """Move the advices already in flight onto the new routes.

    Every draft was sitting in the retired "Pending Approval" state, which the new workflow
    does not define — left alone they would have no transitions at all and could never be
    approved. Each one is re-stamped with the route its own references imply and moved to that
    route's first state, and the actions belonging to the old state are closed so nobody is
    asked twice.

    Runs as a dry run by default: pass dry_run=0 to write. Replaying it is safe — an advice
    already sitting in a state the new workflow defines is left exactly as it is.
    """
    frappe.only_for(("System Manager", "Accounts Manager"))

    from vansale.sf_trading.doctype.payment_advice.payment_advice import compute_approval_route

    live_states = set(ROUTE_ENTRY_STATE.values()) | {STATE_DRAFT, STATE_REJECTED, STATE_APPROVED}
    planned = []

    for name in frappe.get_all("Payment Advice", filters={"docstatus": 0}, pluck="name"):
        advice = frappe.get_doc("Payment Advice", name)
        route = compute_approval_route(advice)
        target = ROUTE_ENTRY_STATE[route]
        current = advice.get("workflow_state")
        stored_route = advice.get("approval_route")

        # Every open advice needs its route stamped, whether or not its state moves. An advice
        # saved before the field existed carries no route, and every transition out of Draft
        # tests that field — so without this the raiser is offered nothing at all and the advice
        # cannot be sent for approval. (Administrator is exempt from condition checks, which is
        # exactly why this is easy to miss when testing as Administrator.)
        needs_route = (stored_route or None) != route
        moves = current not in live_states

        planned.append({
            "advice": name,
            "route": route,
            "from": current,
            "to": target if moves else current,
            "action": ", ".join(
                filter(None, [
                    "moved" if moves else None,
                    "route stamped" if needs_route else None,
                ])
            ) or "left alone — already routed and on a live state",
        })

        if cint(dry_run) or not (needs_route or moves):
            continue

        # the route first, so the workflow's conditions agree with where it is being put
        update = {"approval_route": route}
        if moves:
            update["workflow_state"] = target
        frappe.db.set_value("Payment Advice", name, update, update_modified=False)

        if not moves:
            continue

        # close what belonged to the retired state — those actions can never be completed
        stale = frappe.get_all(
            "PM Workflow Action",
            filters={
                "reference_doctype": DOCTYPE,
                "reference_name": name,
                "status": ["in", ["Open", "Forwarded"]],
                "workflow_state": ["not in", list(live_states)],
            },
            pluck="name",
        )
        for action in stale:
            frappe.db.set_value("PM Workflow Action", action, {
                "status": "Completed",
                "completed_by": frappe.session.user,
            }, update_modified=False)

        # and let the engine raise the actions for the state it is now in
        try:
            from permission_manager.permission_manager.doctype.pm_workflow_action.pm_workflow_action import (
                process_workflow_actions,
            )

            advice.reload()
            process_workflow_actions(advice, "on_update")
        except Exception:
            frappe.log_error(
                message=frappe.get_traceback(),
                title="sf_trading: could not raise workflow actions for %s" % name,
            )

    if not cint(dry_run):
        frappe.db.commit()

    return {
        "dry_run": bool(cint(dry_run)),
        "moved": len([p for p in planned if "moved" in p["action"]]),
        "routed": len([p for p in planned if "route stamped" in p["action"]]),
        "count": len([p for p in planned if p["action"].startswith(("moved", "route stamped"))]),
        "advices": planned,
    }


@frappe.whitelist()
def workflow_status():
    """What the desk should tell a user about advice approval on this site."""
    if not pm_workflow_available():
        return {"available": False, "active": False, "reason": _("permission_manager not installed")}

    workflow = frappe.db.get_value(
        "PM Workflow",
        {"document_type": DOCTYPE},
        ["name", "is_active", "company"],
        as_dict=True,
    )
    if not workflow:
        return {"available": True, "active": False, "reason": _("No workflow created yet")}

    return {
        "available": True,
        "active": bool(cint(workflow.is_active)),
        "workflow": workflow.name,
        "company": workflow.company,
    }
