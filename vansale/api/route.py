"""Daily route planning + visit lifecycle."""

from __future__ import annotations

from datetime import date
from typing import Optional

import frappe
from frappe import _

from vansale.api.datetime_util import naive_site_to_utc_iso, parse_client_ts


@frappe.whitelist(methods=["GET"])
def today() -> dict:
    """Return today's plan (or the next upcoming plan) for the current user."""
    user = frappe.session.user
    plan_name = frappe.db.get_value(
        "Van Route Plan",
        {"user": user, "plan_date": [">=", date.today()]},
        "name",
        order_by="plan_date asc",
    )
    if not plan_name:
        return {"plan": None, "stops": []}
    doc = frappe.get_doc("Van Route Plan", plan_name)
    return {
        "plan": {
            "name": doc.name,
            "plan_date": str(doc.plan_date),
            "warehouse": doc.warehouse,
            "notes": doc.notes,
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


@frappe.whitelist(methods=["POST"])
def start_visit(plan_name: str, stop_idx: int) -> dict:
    if not plan_name:
        frappe.throw(_("plan_name required"))
    doc = frappe.get_doc("Van Route Plan", plan_name)
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


@frappe.whitelist(methods=["GET"])
def daily_report(plan_date: Optional[str] = None) -> dict:
    user = frappe.session.user
    when = plan_date or str(date.today())
    plan_name = frappe.db.get_value("Van Route Plan", {"user": user, "plan_date": when}, "name")
    if not plan_name:
        return {"plan_date": when, "visits": 0, "sales": 0.0, "collections": 0.0, "returns": 0.0, "stops": []}
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
        "plan_date": when,
        "visits": int(visits),
        "sales": float(invoices or 0),
        "collections": float(payments or 0),
        "returns": float(returns or 0),
        "stop_count": len(stop_names),
    }
