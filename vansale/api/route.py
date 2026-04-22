"""Van Sales — daily visit lifecycle (customer-keyed, plan-free).

Design, 2026-04-22: the old Van Route Plan doctype and its stops child
table are gone. A driver's day is just "every customer tagged to my
Sales Person, ordered by the Customer's `custom_van_sort_order`". Each
visit action (start/end/skip) upserts a Van Daily Visit row keyed by
(user, customer, visit_date). This keeps admins out of the route-plan
maintenance loop — they tag a customer's Sales Team once and the
customer shows up in the driver's list from then on.

Offline + idempotency: `end_visit` still writes an immutable Van Visit
Log row keyed by `client_id` so replays from the offline queue are
safe. The Van Daily Visit row is the live editable state; the log is
the audit trail.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Optional

import frappe
from frappe import _

from vansale.api.datetime_util import naive_site_to_utc_iso, parse_client_ts
from vansale.api.me import user_to_sales_person


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _parse_iso_date(raw: str | None) -> date | None:
    """Parse a YYYY-MM-DD string from the client; silently accept None.

    The PWA sends its own local date with every request because the
    server timezone can lag the driver's phone by hours (user report
    2026-04-22: CEST server still on Apr 21 while Riyadh phone was
    already on Apr 22). When client_date is present we trust it.
    """
    if not raw:
        return None
    try:
        parts = raw.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None


def _resolve_sales_person(user: str | None) -> str | None:
    """Current driver's Sales Person — or None if they're not a van user."""
    return user_to_sales_person(user)


def _list_customers_for_sales_person(sales_person: str) -> list[dict]:
    """Customers whose Sales Team row references this Sales Person.

    Ordered by `custom_van_sort_order` asc (nulls last → `COALESCE, big
    number`), then by customer_name for stability. Disabled customers
    are excluded; drivers never see a deactivated account.
    """
    return frappe.db.sql(
        """
        SELECT DISTINCT
            c.name AS customer,
            c.customer_name AS customer_name,
            c.mobile_no AS mobile_no,
            c.customer_primary_address AS primary_address,
            COALESCE(c.custom_van_sort_order, 999999) AS sort_order
        FROM `tabCustomer` c
        INNER JOIN `tabSales Team` st
            ON st.parent = c.name AND st.parenttype = 'Customer'
        WHERE st.sales_person = %s AND c.disabled = 0
        ORDER BY sort_order ASC, c.customer_name ASC
        """,
        (sales_person,),
        as_dict=True,
    )


def _fetch_visit(user: str, customer: str, visit_date: date) -> dict | None:
    """Return the Van Daily Visit state for (user, customer, date), or None."""
    row = frappe.db.get_value(
        "Van Daily Visit",
        {"user": user, "customer": customer, "visit_date": visit_date},
        [
            "name",
            "status",
            "started_at",
            "ended_at",
            "invoice",
            "payment",
            "signature_file",
            "notes",
            "lat",
            "lng",
        ],
        as_dict=True,
    )
    return row


def _upsert_visit(user: str, customer: str, visit_date: date, **fields) -> "frappe.model.document.Document":
    """Get-or-create Van Daily Visit and patch fields. Returns the saved doc.

    We resolve the primary key via `(user, customer, visit_date)` because
    Frappe doctype JSON doesn't support composite unique constraints;
    the uniqueness is enforced here. A race between two simultaneous
    starts on the same customer is still possible but tolerable — the
    second write wins and the Van Visit Log (on end_visit) gives us an
    audit.
    """
    name = frappe.db.get_value(
        "Van Daily Visit",
        {"user": user, "customer": customer, "visit_date": visit_date},
        "name",
    )
    if name:
        doc = frappe.get_doc("Van Daily Visit", name)
    else:
        doc = frappe.new_doc("Van Daily Visit")
        doc.user = user
        doc.customer = customer
        doc.visit_date = visit_date
        doc.status = "pending"
    for k, v in fields.items():
        if v is None and k in {"started_at", "ended_at", "invoice", "payment", "signature_file", "notes", "lat", "lng"}:
            # explicit None allowed — driver cleared a field
            setattr(doc, k, v)
        elif v is not None:
            setattr(doc, k, v)
    doc.save(ignore_permissions=True)
    return doc


def _serialize_stop(customer_row: dict, visit: dict | None, idx: int) -> dict:
    """Merge a live customer row with its current visit state (if any)."""
    if visit:
        return {
            "idx": idx,
            "name": visit["name"],
            "customer": customer_row["customer"],
            "customer_name": customer_row["customer_name"],
            "mobile_no": customer_row.get("mobile_no"),
            "address": customer_row.get("primary_address"),
            "status": visit["status"] or "pending",
            "started_at": naive_site_to_utc_iso(visit["started_at"]),
            "ended_at": naive_site_to_utc_iso(visit["ended_at"]),
            "invoice": visit["invoice"],
            "payment": visit["payment"],
            "signature_file": visit["signature_file"],
            "notes": visit["notes"],
        }
    return {
        "idx": idx,
        "name": None,
        "customer": customer_row["customer"],
        "customer_name": customer_row["customer_name"],
        "mobile_no": customer_row.get("mobile_no"),
        "address": customer_row.get("primary_address"),
        "status": "pending",
        "started_at": None,
        "ended_at": None,
        "invoice": None,
        "payment": None,
        "signature_file": None,
        "notes": None,
    }


# ---------------------------------------------------------------------------
# today + visit lifecycle
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def today(client_date: Optional[str] = None) -> dict:
    """Return the driver's customer list for today.

    Shape:
        {
          "visit_date": "2026-04-22",
          "sales_person": "SP-Ali",
          "stops": [ { customer, customer_name, status, ... }, ... ]
        }

    `plan` is always None — retained in the payload for backwards
    compatibility with older PWA builds that key off it, so an old
    device pointing at this server doesn't crash; new PWA ignores it.
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Login required"))

    today_ = _parse_iso_date(client_date) or date.today()
    sales_person = _resolve_sales_person(user)
    if not sales_person:
        return {
            "visit_date": str(today_),
            "sales_person": None,
            "plan": None,
            "stops": [],
        }

    customers = _list_customers_for_sales_person(sales_person)
    stops: list[dict] = []
    for i, cust in enumerate(customers, start=1):
        visit = _fetch_visit(user, cust["customer"], today_)
        stops.append(_serialize_stop(cust, visit, i))

    return {
        "visit_date": str(today_),
        "sales_person": sales_person,
        "plan": None,  # deprecated placeholder
        "stops": stops,
    }


@frappe.whitelist(methods=["POST"])
def start_visit(customer: str, client_date: Optional[str] = None) -> dict:
    """Mark a visit as in-progress. Upserts the Van Daily Visit row."""
    if not customer:
        frappe.throw(_("customer required"))
    user = frappe.session.user
    today_ = _parse_iso_date(client_date) or date.today()
    now = frappe.utils.now_datetime()
    doc = _upsert_visit(
        user,
        customer,
        today_,
        status="in_progress",
        started_at=now,
    )
    frappe.db.commit()
    return {"name": doc.name, "started_at": naive_site_to_utc_iso(doc.started_at)}


@frappe.whitelist(methods=["POST"])
def end_visit(
    client_id: str,
    customer: str,
    client_date: Optional[str] = None,
    invoice: Optional[str] = None,
    payment: Optional[str] = None,
    signature_file: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    notes: Optional[str] = None,
    posting_ts: Optional[str] = None,
) -> dict:
    """Close a visit. Idempotent by `client_id` via Van Visit Log."""
    if not client_id:
        frappe.throw(_("client_id required"))
    if not customer:
        frappe.throw(_("customer required"))

    # Idempotency: if a log with this client_id exists, replay its output.
    existing_log = frappe.db.get_value(
        "Van Visit Log",
        {"client_id": client_id},
        ["name", "customer"],
        as_dict=True,
    )
    if existing_log:
        return {"name": existing_log.name, "idempotent_replay": True}

    user = frappe.session.user
    today_ = _parse_iso_date(client_date) or date.today()
    ended = parse_client_ts(posting_ts) if posting_ts else frappe.utils.now_datetime()

    doc = _upsert_visit(
        user,
        customer,
        today_,
        status="done",
        ended_at=ended,
        invoice=invoice,
        payment=payment,
        signature_file=signature_file,
        notes=notes,
        lat=lat,
        lng=lng,
    )

    # Audit log — immutable, keyed by client_id for offline replay safety.
    log = frappe.new_doc("Van Visit Log")
    log.client_id = client_id
    log.customer = customer
    log.user = user
    log.started_at = doc.started_at
    log.ended_at = ended
    log.lat = lat
    log.lng = lng
    log.invoice = invoice
    log.payment = payment
    log.signature_file = signature_file
    log.notes = notes
    log.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"name": log.name, "visit": doc.name, "idempotent_replay": False}


@frappe.whitelist(methods=["POST"])
def skip_visit(
    customer: str,
    reason: Optional[str] = None,
    client_date: Optional[str] = None,
) -> dict:
    """Mark a visit as skipped. Idempotent — skipping twice is a no-op."""
    if not customer:
        frappe.throw(_("customer required"))
    user = frappe.session.user
    today_ = _parse_iso_date(client_date) or date.today()

    existing = _fetch_visit(user, customer, today_)
    if existing and existing["status"] in ("done", "skipped"):
        return {"status": existing["status"], "idempotent_replay": True, "name": existing["name"]}

    note = reason or None
    if existing and existing.get("notes"):
        note = f"{existing['notes']}\n{reason}".strip() if reason else existing["notes"]

    doc = _upsert_visit(
        user,
        customer,
        today_,
        status="skipped",
        ended_at=frappe.utils.now_datetime(),
        notes=note,
    )
    frappe.db.commit()
    return {"status": "skipped", "idempotent_replay": False, "name": doc.name}


# ---------------------------------------------------------------------------
# daily report
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def daily_report(client_date: Optional[str] = None, plan_date: Optional[str] = None) -> dict:
    """Aggregate today's visits for the logged-in driver.

    Accepts both `client_date` (new name) and `plan_date` (legacy PWA
    parameter) so old clients still work during rollout.
    """
    user = frappe.session.user
    raw = client_date or plan_date
    today_ = _parse_iso_date(raw) or date.today()

    visits = frappe.db.sql(
        """
        SELECT status, invoice, payment
        FROM `tabVan Daily Visit`
        WHERE user = %s AND visit_date = %s
        """,
        (user, today_),
        as_dict=True,
    )
    stop_count = len(visits)
    done_visits = [v for v in visits if v.status in ("done", "skipped")]

    invoice_names = [v.invoice for v in visits if v.invoice]
    payment_names = [v.payment for v in visits if v.payment]

    sales = 0.0
    returns = 0.0
    if invoice_names:
        placeholders = ", ".join(["%s"] * len(invoice_names))
        sales_row = frappe.db.sql(
            f"SELECT COALESCE(SUM(grand_total), 0) FROM `tabSales Invoice` WHERE name IN ({placeholders}) AND is_return = 0",
            tuple(invoice_names),
        )
        sales = float(sales_row[0][0] or 0)
        returns_row = frappe.db.sql(
            f"SELECT COALESCE(SUM(ABS(grand_total)), 0) FROM `tabSales Invoice` WHERE name IN ({placeholders}) AND is_return = 1",
            tuple(invoice_names),
        )
        returns = float(returns_row[0][0] or 0)

    collections = 0.0
    if payment_names:
        placeholders = ", ".join(["%s"] * len(payment_names))
        pay_row = frappe.db.sql(
            f"SELECT COALESCE(SUM(paid_amount), 0) FROM `tabPayment Entry` WHERE name IN ({placeholders})",
            tuple(payment_names),
        )
        collections = float(pay_row[0][0] or 0)

    return {
        "plan_date": str(today_),
        "visits": len(done_visits),
        "sales": sales,
        "collections": collections,
        "returns": returns,
        "stop_count": stop_count,
    }


# ---------------------------------------------------------------------------
# admin: customer assignment
# ---------------------------------------------------------------------------


@frappe.whitelist()
def customer_query(
    doctype: str,
    txt: str,
    searchfield: str,
    start: int,
    page_len: int,
    filters: dict | None = None,
):
    """Search-as-you-type customer picker filtered by sales_person.

    Used by the Van Customer Assignment page. When `filters.user` is
    given we resolve to that user's Sales Person via Vansale
    Configuration and return matching customers; otherwise return every
    active customer so admins who haven't set up mapping yet can still
    pick. When `filters.unassigned_only` is truthy we return customers
    with NO Sales Team row for the resolved sales_person (handy for the
    "add these customers" workflow).
    """
    filters = filters or {}
    user = filters.get("user")
    sales_person = filters.get("sales_person") or (user_to_sales_person(user) if user else None)
    unassigned_only = bool(filters.get("unassigned_only"))
    txt_like = f"%{txt or ''}%"

    if not sales_person:
        return frappe.db.sql(
            """
            SELECT name, customer_name, mobile_no
            FROM `tabCustomer`
            WHERE disabled = 0
              AND (name LIKE %(t)s OR customer_name LIKE %(t)s OR mobile_no LIKE %(t)s)
            ORDER BY modified DESC LIMIT %(s)s, %(p)s
            """,
            {"t": txt_like, "s": int(start or 0), "p": int(page_len or 20)},
        )

    if unassigned_only:
        return frappe.db.sql(
            """
            SELECT c.name, c.customer_name, c.mobile_no
            FROM `tabCustomer` c
            WHERE c.disabled = 0
              AND (c.name LIKE %(t)s OR c.customer_name LIKE %(t)s OR c.mobile_no LIKE %(t)s)
              AND NOT EXISTS (
                SELECT 1 FROM `tabSales Team` st
                WHERE st.parent = c.name AND st.parenttype = 'Customer'
                  AND st.sales_person = %(sp)s
              )
            ORDER BY c.modified DESC LIMIT %(s)s, %(p)s
            """,
            {"sp": sales_person, "t": txt_like, "s": int(start or 0), "p": int(page_len or 20)},
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
        {"sp": sales_person, "t": txt_like, "s": int(start or 0), "p": int(page_len or 20)},
    )


@frappe.whitelist(methods=["GET"])
def list_customers_for_user(user: Optional[str] = None) -> list[dict]:
    """Return every customer currently assigned to `user`'s Sales Person.

    Used by the admin assignment page to render the "currently assigned"
    chips alongside the picker. Falls back to the session user when no
    user is specified so a driver can self-inspect.
    """
    u = user or frappe.session.user
    if frappe.session.user != u:
        roles = frappe.get_roles(frappe.session.user)
        if not {"System Manager", "Van Manager"} & set(roles):
            frappe.throw(_("Not permitted"))
    sp = user_to_sales_person(u)
    if not sp:
        return []
    return _list_customers_for_sales_person(sp)


@frappe.whitelist(methods=["POST"])
def bulk_assign_sales_person(
    sales_person: Optional[str] = None,
    user: Optional[str] = None,
    customers: list | str | None = None,
    percentage: float = 100,
) -> dict:
    """Append Sales Team row on multiple customers — idempotent.

    Either `sales_person` or `user` must be given. When only `user` is
    given we resolve via Vansale Configuration so the admin can pick the
    driver, not the (often opaque) sales_person id.
    """
    _require_manager()
    sp = sales_person or (user_to_sales_person(user) if user else None)
    if not sp:
        frappe.throw(_("sales_person or user with mapping required"))

    customer_list = _coerce_customer_list(customers)
    if not customer_list:
        return {"assigned": 0, "skipped": 0}

    assigned = 0
    skipped = 0
    for customer in customer_list:
        doc = frappe.get_doc("Customer", customer)
        if any((row.sales_person or "") == sp for row in (doc.sales_team or [])):
            skipped += 1
            continue
        doc.append("sales_team", {
            "sales_person": sp,
            "allocated_percentage": percentage,
        })
        doc.save(ignore_permissions=True)
        assigned += 1
    frappe.db.commit()
    return {"assigned": assigned, "skipped": skipped, "sales_person": sp}


@frappe.whitelist(methods=["POST"])
def bulk_unassign_sales_person(
    sales_person: Optional[str] = None,
    user: Optional[str] = None,
    customers: list | str | None = None,
) -> dict:
    """Remove Sales Team row for `sales_person` from multiple customers."""
    _require_manager()
    sp = sales_person or (user_to_sales_person(user) if user else None)
    if not sp:
        frappe.throw(_("sales_person or user with mapping required"))

    customer_list = _coerce_customer_list(customers)
    if not customer_list:
        return {"unassigned": 0}

    count = 0
    for customer in customer_list:
        doc = frappe.get_doc("Customer", customer)
        removed = False
        for row in list(doc.sales_team or []):
            if (row.sales_person or "") == sp:
                doc.remove(row)
                removed = True
        if removed:
            doc.save(ignore_permissions=True)
            count += 1
    frappe.db.commit()
    return {"unassigned": count, "sales_person": sp}


def _coerce_customer_list(customers: list | str | None) -> list[str]:
    if not customers:
        return []
    if isinstance(customers, str):
        try:
            customers = json.loads(customers)
        except json.JSONDecodeError:
            # Fallback: comma-separated plain string.
            customers = [c.strip() for c in customers.split(",") if c.strip()]
    return [str(c) for c in customers if c]


def _require_manager() -> None:
    roles = frappe.get_roles(frappe.session.user)
    if not ({"System Manager", "Van Manager"} & set(roles)):
        frappe.throw(_("Not permitted"))
