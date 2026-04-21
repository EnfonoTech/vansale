"""Daily route planning + visit lifecycle."""

from __future__ import annotations

import json
from datetime import date
from typing import Optional

import frappe
from frappe import _

from vansale.api.datetime_util import naive_site_to_utc_iso, parse_client_ts


_WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _parse_days(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {d.strip().lower()[:3] for d in raw.split(",") if d.strip()}


def _recurrence_matches(plan: dict, today_: date) -> bool:
    """Does a recurring plan fire today?

    Each frequency has its own rule. For Custom we fall back to
    `interval_days` from the anchor `plan_date`. Plans with `valid_until`
    set are ignored past that date.
    """
    freq = (plan.get("frequency") or "One-time").lower()
    anchor: date | None = plan.get("plan_date")
    valid_until: date | None = plan.get("valid_until")
    if valid_until and today_ > valid_until:
        return False
    if freq == "one-time":
        return anchor == today_
    if not anchor or today_ < anchor:
        return False
    today_key = _WEEKDAY_KEYS[today_.weekday()]
    days = _parse_days(plan.get("days_of_week"))
    if freq == "daily":
        return True
    if freq == "weekly":
        return today_key in days if days else today_.weekday() == anchor.weekday()
    if freq == "biweekly":
        weeks = (today_ - anchor).days // 7
        if weeks % 2 != 0:
            return False
        return today_key in days if days else today_.weekday() == anchor.weekday()
    if freq == "monthly":
        return today_.day == anchor.day
    if freq == "custom":
        interval = int(plan.get("interval_days") or 0)
        if interval <= 0:
            return False
        delta = (today_ - anchor).days
        if delta < 0:
            return False
        if days and today_key not in days:
            return False
        return delta % interval == 0
    return False


def _resolve_todays_plan(user: str) -> str | None:
    """Resolve the plan that fires for `user` today, honouring frequency.

    Order of precedence:
        1. One-time plan with `plan_date == today`
        2. Future one-time plan (earliest upcoming)
        3. Any recurring plan whose rule fires today
    """
    today_ = date.today()
    # (1) exact one-time hit
    name = frappe.db.get_value(
        "Van Route Plan",
        {"user": user, "plan_date": today_, "frequency": ["in", ["One-time", ""]]},
        "name",
    )
    if name:
        return name
    # (3) recurring matches
    candidates = frappe.get_all(
        "Van Route Plan",
        filters={
            "user": user,
            "frequency": ["in", ["Daily", "Weekly", "Biweekly", "Monthly", "Custom"]],
        },
        fields=["name", "frequency", "days_of_week", "interval_days", "plan_date", "valid_until"],
    )
    for c in candidates:
        if _recurrence_matches(c, today_):
            return c["name"]
    # (2) next upcoming one-time
    return frappe.db.get_value(
        "Van Route Plan",
        {"user": user, "plan_date": [">=", today_]},
        "name",
        order_by="plan_date asc",
    )


@frappe.whitelist(methods=["GET"])
def today() -> dict:
    """Return today's plan (or the next upcoming plan) for the current user.

    Respects the Frequency field on Van Route Plan so ops can set up
    "every Monday / Wednesday" or "every 3 days" and the driver's app
    sees the right stops without a fresh plan row per day.

    Also surfaces `status`, `completed_at`, `completion_summary` so the
    app knows whether the driver already closed this route today — prior
    behaviour kept prompting "Complete route?" on every page-open after
    the user had already completed it, because completion wasn't
    persisted on the server.
    """
    user = frappe.session.user
    plan_name = _resolve_todays_plan(user)
    if not plan_name:
        return {"plan": None, "stops": []}
    doc = frappe.get_doc("Van Route Plan", plan_name)
    summary_raw = getattr(doc, "completion_summary", None)
    try:
        summary = json.loads(summary_raw) if summary_raw else None
    except (TypeError, ValueError):
        summary = None
    return {
        "plan": {
            "name": doc.name,
            "route_name": getattr(doc, "route_name", None) or None,
            "plan_date": str(doc.plan_date),
            "warehouse": doc.warehouse,
            "notes": doc.notes,
            "frequency": getattr(doc, "frequency", None) or "One-time",
            "days_of_week": getattr(doc, "days_of_week", None),
            "valid_until": str(doc.valid_until) if getattr(doc, "valid_until", None) else None,
            "status": getattr(doc, "status", None) or "Active",
            "completed_at": naive_site_to_utc_iso(getattr(doc, "completed_at", None)),
            "completion_summary": summary,
        },
        "stops": [
            {
                "idx": s.idx,
                "name": s.name,
                "customer": s.customer,
                "planned_time": str(s.planned_time) if s.planned_time else None,
                "address": s.address,
                "status": s.status,
                "started_at": naive_site_to_utc_iso(s.started_at),
                "ended_at": naive_site_to_utc_iso(s.ended_at),
                "invoice": s.invoice,
                "payment": s.payment,
                "signature_file": s.signature_file,
                "notes": s.notes,
            }
            for s in doc.stops
        ],
    }


@frappe.whitelist(methods=["POST"])
def create_plan(plan_date: str, stops: list[dict], warehouse: Optional[str] = None, notes: Optional[str] = None) -> dict:
    if not plan_date:
        frappe.throw(_("plan_date required"))
    doc = frappe.new_doc("Van Route Plan")
    doc.user = frappe.session.user
    doc.plan_date = plan_date
    doc.warehouse = warehouse
    doc.notes = notes
    for stop in stops:
        if not stop.get("customer"):
            frappe.throw(_("Each stop must have a customer"))
        row = doc.append("stops", {})
        row.customer = stop["customer"]
        row.planned_time = stop.get("planned_time")
        row.address = stop.get("address")
        row.status = "pending"
    doc.insert(ignore_permissions=False)
    frappe.db.commit()
    return {"name": doc.name}


def _guard_plan_not_completed(plan) -> None:
    """Reject per-stop mutations on a Completed plan. Admin re-open path is
    via the Route Plan doctype in Desk (set status back to Active manually).
    """
    if (getattr(plan, "status", None) or "Active") == "Completed":
        frappe.throw(_("Route already completed. Ask ops to reopen it if you need to change a stop."))


@frappe.whitelist(methods=["POST"])
def start_visit(plan_name: str, stop_idx: int) -> dict:
    if not plan_name:
        frappe.throw(_("plan_name required"))
    doc = frappe.get_doc("Van Route Plan", plan_name)
    _guard_plan_not_completed(doc)
    stop = next((s for s in doc.stops if int(s.idx) == int(stop_idx)), None)
    if not stop:
        frappe.throw(_("Stop not found"))
    stop.status = "in_progress"
    stop.started_at = frappe.utils.now_datetime()
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"started_at": naive_site_to_utc_iso(stop.started_at)}


@frappe.whitelist(methods=["POST"])
def end_visit(
    client_id: str,
    plan_name: str,
    stop_idx: int,
    invoice: Optional[str] = None,
    payment: Optional[str] = None,
    signature_file: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    notes: Optional[str] = None,
    posting_ts: Optional[str] = None,
    stop_name: Optional[str] = None,
) -> dict:
    """Close a visit. Records a Van Visit Log, idempotent by ``client_id``."""
    if not client_id:
        frappe.throw(_("client_id required"))
    # Idempotency — reuse stop_name by client_id if already logged.
    if frappe.db.exists("Van Visit Log", {"client_id": client_id}):
        existing = frappe.get_doc("Van Visit Log", {"client_id": client_id})
        return {"name": existing.name, "idempotent_replay": True}

    if not plan_name:
        frappe.throw(_("plan_name required"))
    plan = frappe.get_doc("Van Route Plan", plan_name)
    _guard_plan_not_completed(plan)
    stop = next((s for s in plan.stops if int(s.idx) == int(stop_idx)), None)
    if not stop:
        frappe.throw(_("Stop not found"))

    ended = parse_client_ts(posting_ts) if posting_ts else frappe.utils.now_datetime()
    stop.status = "done"
    stop.ended_at = ended
    stop.invoice = invoice
    stop.payment = payment
    stop.signature_file = signature_file
    stop.notes = notes
    plan.save(ignore_permissions=True)

    log = frappe.new_doc("Van Visit Log")
    log.client_id = client_id
    log.route_plan = plan_name
    log.stop_idx = stop_idx
    log.customer = stop.customer
    log.user = frappe.session.user
    log.started_at = stop.started_at
    log.ended_at = ended
    log.lat = lat
    log.lng = lng
    log.invoice = invoice
    log.payment = payment
    log.signature_file = signature_file
    log.notes = notes
    log.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"name": log.name, "idempotent_replay": False}


@frappe.whitelist(methods=["POST"])
def skip_visit(plan_name: str, stop_idx: int, reason: Optional[str] = None) -> dict:
    """Abandon an in-progress or pending stop. Used to unstick customers left
    dangling in ``in_progress`` when the user backs out without completing
    the visit, or to deliberately skip a stop without creating an invoice.
    Idempotent — calling on an already-skipped or done stop is a no-op.
    """
    if not plan_name:
        frappe.throw(_("plan_name required"))
    plan = frappe.get_doc("Van Route Plan", plan_name)
    _guard_plan_not_completed(plan)
    stop = next((s for s in plan.stops if int(s.idx) == int(stop_idx)), None)
    if not stop:
        frappe.throw(_("Stop not found"))
    if stop.status in ("done", "skipped"):
        return {"status": stop.status, "idempotent_replay": True}
    stop.status = "skipped"
    stop.ended_at = frappe.utils.now_datetime()
    if reason:
        stop.notes = (f"{stop.notes or ''}\n{reason}").strip()
    plan.save(ignore_permissions=True)
    frappe.db.commit()
    return {"status": "skipped", "idempotent_replay": False}


def _compute_daily_report(plan_name: str, plan_date: str) -> dict:
    """Shared daily-report aggregation used by the ``daily_report`` API and the
    ``complete_route`` snapshot. Keeping one implementation avoids the summary
    displayed on reopen drifting from what the driver saw on tap-to-complete.
    """
    doc = frappe.get_doc("Van Route Plan", plan_name)
    stop_names = [s.name for s in doc.stops]
    visits = frappe.db.count("Van Visit Log", {"route_plan": plan_name})
    invoices = frappe.db.sql(
        """
        SELECT COALESCE(SUM(grand_total), 0) FROM `tabSales Invoice`
        WHERE name IN (SELECT invoice FROM `tabVan Visit Log` WHERE route_plan=%s) AND is_return = 0
        """,
        (plan_name,),
    )[0][0]
    returns = frappe.db.sql(
        """
        SELECT COALESCE(SUM(ABS(grand_total)), 0) FROM `tabSales Invoice`
        WHERE name IN (SELECT invoice FROM `tabVan Visit Log` WHERE route_plan=%s) AND is_return = 1
        """,
        (plan_name,),
    )[0][0]
    payments = frappe.db.sql(
        """
        SELECT COALESCE(SUM(paid_amount), 0) FROM `tabPayment Entry`
        WHERE name IN (SELECT payment FROM `tabVan Visit Log` WHERE route_plan=%s)
        """,
        (plan_name,),
    )[0][0]
    return {
        "plan_date": plan_date,
        "visits": int(visits),
        "sales": float(invoices or 0),
        "collections": float(payments or 0),
        "returns": float(returns or 0),
        "stop_count": len(stop_names),
    }


@frappe.whitelist(methods=["GET"])
def daily_report(plan_date: Optional[str] = None) -> dict:
    user = frappe.session.user
    when = plan_date or str(date.today())
    plan_name = frappe.db.get_value("Van Route Plan", {"user": user, "plan_date": when}, "name")
    if not plan_name:
        return {"plan_date": when, "visits": 0, "sales": 0.0, "collections": 0.0, "returns": 0.0, "stop_count": 0}
    return _compute_daily_report(plan_name, when)


@frappe.whitelist(methods=["POST"])
def complete_route(plan_name: str, force: int = 0) -> dict:
    """Mark a route plan as completed and snapshot the daily report.

    The driver's app calls this when the user taps "Complete Route". We
    persist the decision on the server so reopening the plan on the same
    day doesn't prompt "Complete?" again (which was the 2026-04-21
    user-reported bug — the button was client-state-only before).

    Guard: if any stop is still `in_progress`, respond with a list of
    those stops instead of closing. The app surfaces the list to the
    driver and asks them to end those visits first. A caller can pass
    ``force=1`` to skip the guard — used for the deliberate "close
    anyway" escape hatch.
    """
    if not plan_name:
        frappe.throw(_("plan_name required"))
    plan = frappe.get_doc("Van Route Plan", plan_name)
    status = (getattr(plan, "status", None) or "Active")
    if status == "Completed":
        # Re-entry after refresh — just hand back the stored summary.
        raw = getattr(plan, "completion_summary", None)
        try:
            summary = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            summary = None
        return {
            "status": "already_completed",
            "completed_at": naive_site_to_utc_iso(getattr(plan, "completed_at", None)),
            "summary": summary,
        }

    in_progress = [
        {"idx": int(s.idx), "customer": s.customer}
        for s in plan.stops
        if s.status == "in_progress"
    ]
    if in_progress and not int(force or 0):
        return {
            "status": "blocked",
            "reason": "in_progress",
            "in_progress_stops": in_progress,
        }

    summary = _compute_daily_report(plan.name, str(plan.plan_date))
    plan.status = "Completed"
    plan.completed_at = frappe.utils.now_datetime()
    plan.completion_summary = json.dumps(summary)
    plan.save(ignore_permissions=True)
    frappe.db.commit()
    return {
        "status": "completed",
        "completed_at": naive_site_to_utc_iso(plan.completed_at),
        "summary": summary,
    }
