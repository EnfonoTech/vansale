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
from frappe.utils import getdate, nowdate
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


VALID_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _weekday_code(d: date) -> str:
    """ISO weekday → three-letter lowercase code. Matches `custom_visit_days`."""
    return VALID_WEEKDAYS[d.weekday()]


def _customer_runs_today(visit_days_csv: str | None, today_: date) -> bool:
    """True iff a customer's visit_days CSV covers `today_`.

    Empty / None means every day (backwards compatible). Unknown codes
    are silently ignored so a stray value doesn't silently hide a
    customer from the driver.
    """
    if not visit_days_csv or not visit_days_csv.strip():
        return True
    needle = _weekday_code(today_)
    days = {p.strip().lower() for p in visit_days_csv.split(",") if p.strip()}
    return needle in days


def _list_customers_for_sales_person(
    sales_person: str,
    visit_date: date | None = None,
) -> list[dict]:
    """Customers linked to this Sales Person (Sales Team, or
    Customer.custom_sales_person where the site has it).

    Ordered by `custom_van_sort_order` asc (nulls last → `COALESCE, big
    number`), then by customer_name for stability. Disabled customers
    are excluded; drivers never see a deactivated account.

    When `visit_date` is given, customers whose `custom_visit_days` CSV
    does not include that weekday are filtered out. When it's None we
    return every tagged customer regardless of schedule — used by the
    admin assignment page so operators can see and edit the full roster.
    """
    from vansale.api.customer import _sales_person_customers

    names = _sales_person_customers(sales_person)
    if not names:
        return []
    rows = frappe.db.sql(
        """
        SELECT
            c.name AS customer,
            c.customer_name AS customer_name,
            c.mobile_no AS mobile_no,
            c.customer_primary_address AS primary_address,
            COALESCE(c.custom_van_sort_order, 999999) AS sort_order,
            c.custom_visit_days AS visit_days
        FROM `tabCustomer` c
        WHERE c.name IN %(names)s AND c.disabled = 0
        ORDER BY sort_order ASC, c.customer_name ASC
        """,
        {"names": tuple(names)},
        as_dict=True,
    )
    if visit_date is None:
        return rows
    return [r for r in rows if _customer_runs_today(r.get("visit_days"), visit_date)]


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

    today_ = _parse_iso_date(client_date) or getdate(nowdate())
    sales_person = _resolve_sales_person(user)
    if not sales_person:
        return {
            "visit_date": str(today_),
            "sales_person": None,
            "plan": None,
            "stops": [],
        }

    customers = _list_customers_for_sales_person(sales_person, visit_date=today_)
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
    today_ = _parse_iso_date(client_date) or getdate(nowdate())
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
    today_ = _parse_iso_date(client_date) or getdate(nowdate())
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
    today_ = _parse_iso_date(client_date) or getdate(nowdate())

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
    today_ = _parse_iso_date(raw) or getdate(nowdate())

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
    # Manager page only: it lists every customer with mobile numbers.
    _require_manager()
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


@frappe.whitelist()
def van_user_query(
    doctype: str = "User",
    txt: str = "",
    searchfield: str = "name",
    start: int = 0,
    page_len: int = 20,
    filters: dict | None = None,
):
    """Link-field query: return only Users that appear in Vansale
    Configuration User rows. Used by the assignment page so admins can't
    pick a random User who has no Sales Person mapping.

    Frappe's Link control calls this with its standard signature —
    we ignore `doctype`, `filters`, and return `[(name, label), ...]`.
    """
    _require_manager()
    txt_like = f"%{txt or ''}%"
    return frappe.db.sql(
        """
        SELECT DISTINCT u.name, CONCAT(u.full_name, ' · ', COALESCE(vcu.sales_person, '-'))
        FROM `tabVansale Configuration User` vcu
        JOIN `tabUser` u ON u.name = vcu.user
        WHERE u.enabled = 1
          AND (u.name LIKE %(t)s OR u.full_name LIKE %(t)s OR vcu.sales_person LIKE %(t)s)
        ORDER BY u.full_name ASC
        LIMIT %(s)s, %(p)s
        """,
        {"t": txt_like, "s": int(start or 0), "p": int(page_len or 20)},
    )


@frappe.whitelist()
def list_available_customers(
    sales_person: str,
    include_assigned: int = 0,
    search: str | None = None,
    limit: int = 0,
) -> list[dict]:
    """Pool of customers for the right-side picker.

    Default (include_assigned=0): customers with no Sales Team rows at all
    OR with only this sales_person (latter are already on this roster so
    the UI filters them out via `assigned_set`). We specifically exclude
    customers assigned to a DIFFERENT sales_person so the admin doesn't
    accidentally double-book.

    include_assigned=1: return every active customer and include an
    `assigned_to` field listing the other sales_persons already tagged.
    The UI shows these with a "reassign" button — clicking calls
    `reassign_customer_sales_person` which atomically wipes prior
    sales_team rows before the normal bulk_assign path runs.
    """
    _require_manager()
    if not sales_person:
        return []
    search_like = f"%{(search or '').strip()}%"
    lim = int(limit or 0)
    lim_clause = f"LIMIT {lim}" if lim > 0 else ""

    if int(include_assigned or 0):
        rows = frappe.db.sql(
            f"""
            SELECT c.name AS customer,
                   c.customer_name AS customer_name,
                   c.mobile_no AS mobile_no,
                   GROUP_CONCAT(DISTINCT st.sales_person) AS assigned_to
            FROM `tabCustomer` c
            LEFT JOIN `tabSales Team` st
                ON st.parent = c.name AND st.parenttype = 'Customer'
            WHERE c.disabled = 0
              AND (c.name LIKE %(s)s OR c.customer_name LIKE %(s)s OR c.mobile_no LIKE %(s)s)
            GROUP BY c.name, c.customer_name, c.mobile_no
            ORDER BY c.customer_name ASC
            {lim_clause}
            """,
            {"s": search_like},
            as_dict=True,
        )
    else:
        # Exclude customers tagged with a different sales person. Customers
        # with NO sales_team rows are kept; customers with only this
        # sales_person are kept (they'll be filtered client-side because
        # they're already on the roster).
        rows = frappe.db.sql(
            f"""
            SELECT c.name AS customer,
                   c.customer_name AS customer_name,
                   c.mobile_no AS mobile_no,
                   NULL AS assigned_to
            FROM `tabCustomer` c
            WHERE c.disabled = 0
              AND (c.name LIKE %(s)s OR c.customer_name LIKE %(s)s OR c.mobile_no LIKE %(s)s)
              AND NOT EXISTS (
                SELECT 1 FROM `tabSales Team` st
                WHERE st.parent = c.name AND st.parenttype = 'Customer'
                  AND st.sales_person != %(sp)s
              )
            ORDER BY c.customer_name ASC
            {lim_clause}
            """,
            {"s": search_like, "sp": sales_person},
            as_dict=True,
        )
    return rows


@frappe.whitelist(methods=["POST"])
def reassign_customer_sales_person(
    customer: str,
    sales_person: str,
    percentage: float = 100,
) -> dict:
    """Atomically move a customer from their current sales_person(s) to a
    new one. Strips all prior Sales Team rows then inserts a single fresh
    row for `sales_person`. Bypasses Customer.save to dodge mandatory
    validation on unrelated fields (e.g. Customer Country)."""
    _require_manager()
    if not customer or not sales_person:
        frappe.throw(_("customer and sales_person required"))
    frappe.db.sql(
        """DELETE FROM `tabSales Team`
           WHERE parent = %s AND parenttype = 'Customer'""",
        (customer,),
    )
    row = frappe.new_doc("Sales Team")
    row.parent = customer
    row.parenttype = "Customer"
    row.parentfield = "sales_team"
    row.idx = 1
    row.sales_person = sales_person
    row.allocated_percentage = percentage
    row.db_insert()
    frappe.db.sql(
        "UPDATE `tabCustomer` SET modified=%s WHERE name=%s",
        (frappe.utils.now(), customer),
    )
    frappe.db.commit()
    return {"customer": customer, "sales_person": sales_person}


@frappe.whitelist()
def driver_roster_overview() -> list[dict]:
    """Flat list for the Van Driver Roster viewer: every Vansale user ×
    their customers. Ordered by (user, customer_name). Empty drivers get
    a single row with customer=None so the viewer can show "no
    customers" for them explicitly rather than hiding them."""
    _require_manager()
    rows = frappe.db.sql(
        """
        SELECT vcu.user AS user,
               u.full_name AS full_name,
               vcu.sales_person AS sales_person,
               c.name AS customer,
               c.customer_name AS customer_name,
               c.mobile_no AS mobile_no,
               c.custom_visit_days AS visit_days
        FROM `tabVansale Configuration User` vcu
        JOIN `tabUser` u ON u.name = vcu.user
        LEFT JOIN `tabSales Team` st
            ON st.sales_person = vcu.sales_person AND st.parenttype = 'Customer'
        LEFT JOIN `tabCustomer` c
            ON c.name = st.parent AND c.disabled = 0
        WHERE u.enabled = 1 AND vcu.sales_person IS NOT NULL AND vcu.sales_person != ''
        ORDER BY u.full_name ASC, c.customer_name ASC
        """,
        as_dict=True,
    )
    return rows


@frappe.whitelist()
def resolve_user_sales_person(user: str) -> dict:
    """Resolve a driver's Sales Person without exposing the
    `Vansale Configuration User` child doctype (which inherits its
    permissions from the System-Manager-only Vansale Configuration
    parent) to Van Manager role users."""
    _require_manager()
    if not user:
        return {"user": None, "sales_person": None}
    return {"user": user, "sales_person": user_to_sales_person(user)}


@frappe.whitelist()
def list_assigned_customers(sales_person: str) -> list[dict]:
    """Customers currently tagged to `sales_person`.

    Mirrors `_list_customers_for_sales_person` under a manager-gated
    endpoint so the admin assignment page doesn't have to hit
    `frappe.client.get_list` (which is permission-checked per role and
    fails for Van Manager without explicit Customer DocPerms).

    Admin view — returns the full roster regardless of today's weekday
    so operators see every assignment they can edit.
    """
    _require_manager()
    if not sales_person:
        return []
    return _list_customers_for_sales_person(sales_person, visit_date=None)


def _normalize_visit_days(days: list | str | None) -> str:
    """Coerce incoming days payload to canonical `mon,tue,wed` CSV."""
    if days is None:
        return ""
    if isinstance(days, str):
        try:
            parsed = json.loads(days)
            if isinstance(parsed, list):
                days = parsed
            else:
                days = [p.strip() for p in days.split(",") if p.strip()]
        except json.JSONDecodeError:
            days = [p.strip() for p in days.split(",") if p.strip()]
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in days or []:
        code = str(raw).strip().lower()
        if code in VALID_WEEKDAYS and code not in seen:
            cleaned.append(code)
            seen.add(code)
    return ",".join(cleaned)


@frappe.whitelist(methods=["POST"])
def set_customer_visit_days(customer: str, days: list | str | None = None) -> dict:
    """Write `custom_visit_days` on a single Customer."""
    _require_manager()
    if not customer:
        frappe.throw(_("customer required"))
    canonical = _normalize_visit_days(days)
    frappe.db.set_value("Customer", customer, "custom_visit_days", canonical, update_modified=True)
    frappe.db.commit()
    return {"customer": customer, "visit_days": canonical}


@frappe.whitelist(methods=["POST"])
def bulk_set_visit_days(customers: list | str | None = None, days: list | str | None = None) -> dict:
    """Write `custom_visit_days` on many customers in one call."""
    _require_manager()
    customer_list = _coerce_customer_list(customers)
    if not customer_list:
        return {"updated": 0, "visit_days": ""}
    canonical = _normalize_visit_days(days)
    for c in customer_list:
        frappe.db.set_value("Customer", c, "custom_visit_days", canonical, update_modified=True)
    frappe.db.commit()
    return {"updated": len(customer_list), "visit_days": canonical}


@frappe.whitelist()
def customer_summary(customer: str) -> dict:
    """Name + phone for a single customer — manager-gated, used by the
    assignment page to label freshly picked customers."""
    _require_manager()
    if not customer:
        return {}
    row = frappe.db.get_value(
        "Customer",
        customer,
        ["customer_name", "mobile_no"],
        as_dict=True,
    )
    return row or {}


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
    now = frappe.utils.now()
    for customer in customer_list:
        # Direct child-table insert bypasses Customer.save — which would
        # otherwise trip on unrelated mandatory fields (e.g. customer
        # country) on legacy rows and block the whole batch.
        existing = frappe.db.exists(
            "Sales Team",
            {"parent": customer, "parenttype": "Customer", "sales_person": sp},
        )
        if existing:
            skipped += 1
            continue
        max_idx = frappe.db.sql(
            """SELECT COALESCE(MAX(idx), 0) FROM `tabSales Team`
               WHERE parent = %s AND parenttype = 'Customer'""",
            (customer,),
        )[0][0]
        row = frappe.new_doc("Sales Team")
        row.parent = customer
        row.parenttype = "Customer"
        row.parentfield = "sales_team"
        row.idx = (max_idx or 0) + 1
        row.sales_person = sp
        row.allocated_percentage = percentage
        row.db_insert()
        frappe.db.sql(
            "UPDATE `tabCustomer` SET modified=%s WHERE name=%s",
            (now, customer),
        )
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
    now = frappe.utils.now()
    for customer in customer_list:
        # Same direct-delete approach as bulk_assign_sales_person: never
        # load the Customer doc, so mandatory-field validation on
        # unrelated fields can't block an unassignment.
        deleted = frappe.db.sql(
            """DELETE FROM `tabSales Team`
               WHERE parent = %s AND parenttype = 'Customer'
                 AND sales_person = %s""",
            (customer, sp),
        )
        affected = frappe.db.sql("SELECT ROW_COUNT()")[0][0]
        if affected:
            frappe.db.sql(
                "UPDATE `tabCustomer` SET modified=%s WHERE name=%s",
                (now, customer),
            )
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
