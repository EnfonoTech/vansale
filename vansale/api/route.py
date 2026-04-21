"""Daily route planning + visit lifecycle."""

from __future__ import annotations

import json
from datetime import date
from typing import Optional

import frappe
from frappe import _

from vansale.api.datetime_util import naive_site_to_utc_iso, parse_client_ts


_WEEKDAY_CHECK_FIELDS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _parse_days_of_month(raw: str | None) -> set[int]:
    """Parse the CSV `days_of_month` free-text field into a set of ints.

    Invalid tokens silently dropped — the field is human-edited so we'd
    rather show the driver a route than crash on a typo like "1, 15,,".
    """
    if not raw:
        return set()
    out: set[int] = set()
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            n = int(tok)
        except ValueError:
            continue
        if 1 <= n <= 31:
            out.add(n)
    return out


def _recurrence_matches(plan: dict, today_: "date") -> bool:
    """Does a recurring plan fire today?

    Weekly: one of the 7 per-day Check fields (mon..sun) is set AND the
    current weekday matches. Monthly: today's day-of-month is in the
    CSV `days_of_month` list. An optional `plan_date` gates "not before
    this date" so admins can schedule a route to start next month.
    """
    anchor: date | None = plan.get("plan_date")
    if anchor and today_ < anchor:
        return False
    freq = (plan.get("frequency") or "Weekly")
    if freq == "Weekly":
        today_field = _WEEKDAY_CHECK_FIELDS[today_.weekday()]
        return bool(plan.get(today_field))
    if freq == "Monthly":
        return today_.day in _parse_days_of_month(plan.get("days_of_month"))
    return False


def _parse_iso_date(raw: str | None) -> date | None:
    """Parse a YYYY-MM-DD string from the client; silently accept None."""
    if not raw:
        return None
    try:
        parts = raw.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None


def _auto_reopen_for_new_day(doc, today_: date) -> None:
    """Reset a Completed plan to Active when it fires again on a later day.

    Recurring plans share a single doctype row across every occurrence
    (every Mon/Wed/Fri for the same Weekly plan). Without this reset a
    route completed on Monday would still look Completed when the driver
    opens the app on Wednesday.

    Stop statuses are also reset so pending/done/skipped don't leak
    across occurrences. completion_summary is preserved on the row for
    historical audit \u2014 it's cleared when the new occurrence closes.
    """
    if (getattr(doc, "status", None) or "Active") != "Completed":
        return
    completed_at = getattr(doc, "completed_at", None)
    if not completed_at:
        return
    completed_date = completed_at.date() if hasattr(completed_at, "date") else None
    if completed_date and completed_date >= today_:
        return  # completed earlier today \u2014 don't reset yet
    doc.status = "Active"
    doc.completed_at = None
    doc.completion_summary = None
    for s in doc.stops:
        s.status = "pending"
        s.started_at = None
        s.ended_at = None
        s.invoice = None
        s.payment = None
        s.signature_file = None
    doc.save(ignore_permissions=True)
    frappe.db.commit()


def _resolve_todays_plan(user: str, today_: date) -> str | None:
    """Resolve the plan that fires for `user` on `today_`.

    Fetches every Active plan for the user and returns the first whose
    recurrence rule matches. Weekly plans win over Monthly (routes are
    usually weekly day-of-week runs and the monthly pattern is the
    fallback for per-month specials like "end-of-month collection").

    `today_` is the driver's local date \u2014 pass it in rather than
    calling `date.today()` here because the server timezone can lag the
    driver's phone by hours (user report 2026-04-22).
    """
    candidates = frappe.get_all(
        "Van Route Plan",
        filters={"user": user},
        fields=[
            "name", "frequency", "plan_date",
            "mon", "tue", "wed", "thu", "fri", "sat", "sun",
            "days_of_month",
        ],
        order_by="frequency asc, modified desc",  # Weekly < Monthly alphabetically
    )
    for c in candidates:
        if _recurrence_matches(c, today_):
            return c["name"]
    return None


@frappe.whitelist(methods=["GET"])
def today(client_date: Optional[str] = None) -> dict:
    """Return today's plan for the current user, by recurrence.

    `client_date` (YYYY-MM-DD) is the driver's **local** date. Server
    time zone can lag the driver's phone by several hours — the 2026-04-22
    user report "today is 22nd and in app showing 21" was exactly this:
    server date.today() was still Apr 21 CEST when the phone rolled into
    Apr 22 IST. When the app sends its own date we trust it.
    """
    user = frappe.session.user
    today_ = _parse_iso_date(client_date) or date.today()
    plan_name = _resolve_todays_plan(user, today_)
    if not plan_name:
        return {"plan": None, "stops": []}
    doc = frappe.get_doc("Van Route Plan", plan_name)
    _auto_reopen_for_new_day(doc, today_)
    summary_raw = getattr(doc, "completion_summary", None)
    try:
        summary = json.loads(summary_raw) if summary_raw else None
    except (TypeError, ValueError):
        summary = None
    return {
        "plan": {
            "name": doc.name,
            "route_name": getattr(doc, "route_name", None) or None,
            "plan_date": str(today_),
            "effective_from": str(doc.plan_date) if getattr(doc, "plan_date", None) else None,
            "warehouse": doc.warehouse,
            "notes": doc.notes,
            "frequency": getattr(doc, "frequency", None) or "Weekly",
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
def create_plan(
    route_name: str,
    stops: list[dict],
    frequency: str = "Weekly",
    days_of_week: list[str] | None = None,
    days_of_month: str | None = None,
    warehouse: Optional[str] = None,
    notes: Optional[str] = None,
    plan_date: Optional[str] = None,
) -> dict:
    """Create a recurring Van Route Plan for the current user.

    `days_of_week` accepts a list of lowercase short keys (mon, tue,
    wed, thu, fri, sat, sun) and maps them onto the corresponding
    Check fields on the doctype. `days_of_month` is a CSV string that
    the doctype validates; we persist it verbatim.
    """
    if not route_name:
        frappe.throw(_("route_name required"))
    if not stops:
        frappe.throw(_("At least one stop required"))
    doc = frappe.new_doc("Van Route Plan")
    doc.route_name = route_name
    doc.user = frappe.session.user
    doc.warehouse = warehouse
    doc.notes = notes
    doc.frequency = frequency
    if plan_date:
        doc.plan_date = plan_date
    if frequency == "Weekly" and days_of_week:
        for key in days_of_week:
            k = key.strip().lower()[:3]
            if k in _WEEKDAY_CHECK_FIELDS:
                setattr(doc, k, 1)
    if frequency == "Monthly" and days_of_month:
        doc.days_of_month = days_of_month
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


@frappe.whitelist()
def customer_query(
    doctype: str,
    txt: str,
    searchfield: str,
    start: int,
    page_len: int,
    filters: dict | None = None,
):
    """Link-field query for the `stops.customer` picker on Van Route Plan.

    Filters the customer list to those whose Sales Team includes the
    plan's Sales User via that user's linked Sales Person (resolved
    through the Vansale Configuration mapping the rest of the codebase
    uses). Admins who haven't mapped the user to a sales person get the
    full customer list \u2014 better than an empty picker with no
    explanation.
    """
    from vansale.api.me import user_to_sales_person

    user = (filters or {}).get("user")
    txt_like = f"%{txt or ''}%"
    # No user picked yet \u2014 admin is still filling the form. Show every
    # active customer so they're not stuck.
    if not user:
        return frappe.db.sql(
            """
            SELECT name, customer_name, mobile_no
            FROM `tabCustomer`
            WHERE disabled = 0 AND (name LIKE %(t)s OR customer_name LIKE %(t)s OR mobile_no LIKE %(t)s)
            ORDER BY modified DESC LIMIT %(s)s, %(p)s
            """,
            {"t": txt_like, "s": int(start or 0), "p": int(page_len or 20)},
        )
    sp = user_to_sales_person(user)
    if not sp:
        # User isn't mapped to a sales person \u2014 fall back to all customers.
        return frappe.db.sql(
            """
            SELECT name, customer_name, mobile_no
            FROM `tabCustomer`
            WHERE disabled = 0 AND (name LIKE %(t)s OR customer_name LIKE %(t)s OR mobile_no LIKE %(t)s)
            ORDER BY modified DESC LIMIT %(s)s, %(p)s
            """,
            {"t": txt_like, "s": int(start or 0), "p": int(page_len or 20)},
        )
    return frappe.db.sql(
        """
        SELECT DISTINCT c.name, c.customer_name, c.mobile_no
        FROM `tabCustomer` c
        JOIN `tabSales Team` st
          ON st.parent = c.name AND st.parenttype = 'Customer'
        WHERE c.disabled = 0
          AND st.sales_person = %(sp)s
          AND (c.name LIKE %(t)s OR c.customer_name LIKE %(t)s OR c.mobile_no LIKE %(t)s)
        ORDER BY c.modified DESC LIMIT %(s)s, %(p)s
        """,
        {"sp": sp, "t": txt_like, "s": int(start or 0), "p": int(page_len or 20)},
    )


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
    """Today's report for the logged-in driver.

    Plans are recurring now (Weekly/Monthly), so `plan_date` is kept as
    a label on the payload for continuity with older PWAs but we always
    resolve the plan via the recurrence rule.
    """
    user = frappe.session.user
    when = plan_date or str(date.today())
    plan_name = _resolve_todays_plan(user)
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

    # plan_date is optional "Effective From" anchor now — fall back to
    # today when it isn't set, so the summary always has a readable date.
    summary_date = str(plan.plan_date) if getattr(plan, "plan_date", None) else str(date.today())
    summary = _compute_daily_report(plan.name, summary_date)
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
