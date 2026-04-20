"""Customer endpoints scoped to the logged-in salesperson."""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _

from vansale.api.datetime_util import naive_site_to_utc_iso


_LIST_FIELDS = [
    "name",
    "customer_name",
    "customer_group",
    "territory",
    "mobile_no",
    "email_id",
    "tax_id",
    "customer_primary_address",
    "default_currency",
    "disabled",
    "modified",
]


def _customer_filters_for_user() -> dict:
    """Return the base filter set for Customer queries.

    Customer-level scoping happens via Frappe's User Permission system
    (Territory, Customer Group) when admins configure it. The Vansale
    Configuration pattern — mirroring RMAX's Branch Configuration —
    doesn't create Customer-level User Permissions, so every Van User
    sees all active customers unless the admin restricts explicitly.
    """
    return {"disabled": 0}


@frappe.whitelist(methods=["GET"])
def list_mine(limit: int = 50, search: Optional[str] = None) -> list[dict]:
    filters = _customer_filters_for_user()
    or_filters = {}
    if search:
        s = f"%{search}%"
        or_filters = {"customer_name": ["like", s], "mobile_no": ["like", s], "tax_id": ["like", s]}
    rows = frappe.get_all(
        "Customer",
        filters=filters,
        or_filters=or_filters or None,
        fields=_LIST_FIELDS,
        limit=int(limit),
        order_by="modified desc",
    )
    for r in rows:
        r["modified"] = naive_site_to_utc_iso(r.get("modified"))
    return rows


@frappe.whitelist(methods=["GET"])
def detail(name: str) -> dict:
    if not name:
        frappe.throw(_("Customer name required"))
    doc = frappe.get_doc("Customer", name)
    addresses = frappe.db.sql(
        """
        SELECT a.name, a.address_line1, a.address_line2, a.city, a.state, a.pincode, a.country,
               a.is_primary_address, a.is_shipping_address, a.phone
        FROM `tabAddress` a
        JOIN `tabDynamic Link` l ON l.parent = a.name
        WHERE l.link_doctype = 'Customer' AND l.link_name = %s
        ORDER BY a.is_primary_address DESC, a.creation DESC
        """,
        (name,),
        as_dict=True,
    )
    outstanding = (
        frappe.db.sql(
            """
            SELECT COALESCE(SUM(outstanding_amount), 0)
            FROM `tabSales Invoice`
            WHERE customer = %s AND docstatus = 1
            """,
            (name,),
        )[0][0]
        or 0
    )
    return {
        "name": doc.name,
        "customer_name": doc.customer_name,
        "customer_group": doc.customer_group,
        "territory": doc.territory,
        "mobile_no": doc.mobile_no,
        "email_id": doc.email_id,
        "tax_id": doc.tax_id,
        "default_currency": doc.default_currency,
        "addresses": addresses,
        "outstanding": float(outstanding or 0),
        "modified": naive_site_to_utc_iso(doc.modified),
    }


@frappe.whitelist(methods=["POST"])
def create(
    customer_name: str,
    mobile_no: str | None = None,
    territory: str | None = None,
    tax_id: str | None = None,
    customer_group: str | None = None,
    customer_type: str | None = None,         # "b2b" | "b2c"
    email_id: str | None = None,
    address_line1: str | None = None,
    address_line2: str | None = None,
    city: str | None = None,
    state: str | None = None,
    pincode: str | None = None,
    country: str | None = None,
) -> dict:
    """Create a Customer + optional primary Address.

    B2B (customer_type="b2b") requires address_line1 + city (per PDF §2b).
    B2C (customer_type="b2c") default — Individual, address optional.
    """
    if not customer_name:
        frappe.throw(_("Customer name required"))
    ctype = (customer_type or "b2c").lower()
    is_b2b = ctype == "b2b"
    if is_b2b and (not address_line1 or not city):
        frappe.throw(_("Address (line 1 + city) is mandatory for B2B customers"))

    doc = frappe.get_doc({
        "doctype": "Customer",
        "customer_name": customer_name,
        "customer_type": "Company" if is_b2b else "Individual",
        "mobile_no": mobile_no,
        "email_id": email_id,
        "territory": territory or frappe.db.get_single_value("Selling Settings", "territory") or "All Territories",
        "customer_group": customer_group or frappe.db.get_single_value("Selling Settings", "customer_group") or "All Customer Groups",
        "tax_id": tax_id,
    })
    doc.insert(ignore_permissions=False)

    # Create Address if fields provided (mandatory for B2B, optional for B2C).
    address_name: str | None = None
    if address_line1:
        addr = frappe.get_doc({
            "doctype": "Address",
            "address_title": customer_name,
            "address_type": "Billing",
            "address_line1": address_line1,
            "address_line2": address_line2,
            "city": city,
            "state": state,
            "pincode": pincode,
            "country": country or frappe.db.get_single_value("Global Defaults", "country") or "Saudi Arabia",
            "phone": mobile_no,
            "email_id": email_id,
            "is_primary_address": 1,
            "is_shipping_address": 1,
            "links": [{"link_doctype": "Customer", "link_name": doc.name}],
        })
        addr.insert(ignore_permissions=False)
        address_name = addr.name
        # Link back to customer as primary address.
        frappe.db.set_value("Customer", doc.name, "customer_primary_address", address_name)

    frappe.db.commit()
    return {
        "name": doc.name,
        "customer_name": doc.customer_name,
        "customer_type": doc.customer_type,
        "address": address_name,
    }


@frappe.whitelist(methods=["GET"])
def statement_html(name: str, from_date: str | None = None, to_date: str | None = None):
    """Render a printable customer statement as HTML.

    Pulls submitted Sales Invoices + Payment Entries for the customer,
    shows running balance per row, opening balance, closing outstanding.
    Opens directly in a browser tab (frappe.response.type="page").
    """
    if not name:
        frappe.throw(_("Customer name required"))
    cust = frappe.get_doc("Customer", name)

    to_date = to_date or str(frappe.utils.today())
    from_date = from_date or frappe.utils.add_days(to_date, -90)

    # Opening balance — sum of GL entries before from_date.
    opening = frappe.db.sql(
        """
        SELECT COALESCE(SUM(debit - credit), 0) AS bal
        FROM `tabGL Entry`
        WHERE party_type = 'Customer' AND party = %s
          AND posting_date < %s AND is_cancelled = 0
        """,
        (name, from_date),
        as_dict=True,
    )
    opening_balance = float(opening[0]["bal"]) if opening else 0.0

    # Invoices in period.
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "customer": name,
            "docstatus": 1,
            "posting_date": ["between", [from_date, to_date]],
        },
        fields=["name", "posting_date", "grand_total", "outstanding_amount", "status", "remarks"],
        order_by="posting_date asc, creation asc",
    )

    # Payments in period.
    payments = frappe.db.sql(
        """
        SELECT pe.name, pe.posting_date, pe.paid_amount,
               pe.mode_of_payment, pe.reference_no
        FROM `tabPayment Entry` pe
        WHERE pe.party_type = 'Customer' AND pe.party = %s
          AND pe.docstatus = 1
          AND pe.posting_date BETWEEN %s AND %s
        ORDER BY pe.posting_date ASC, pe.creation ASC
        """,
        (name, from_date, to_date),
        as_dict=True,
    )

    # Merge into unified ledger sorted by date.
    rows: list[dict] = []
    for inv in invoices:
        rows.append({
            "date": inv.posting_date,
            "ref": inv.name,
            "desc": "Sales Invoice",
            "debit": float(inv.grand_total or 0),
            "credit": 0.0,
        })
    for p in payments:
        rows.append({
            "date": p["posting_date"],
            "ref": p["name"],
            "desc": f"Payment — {p.get('mode_of_payment') or ''}".strip(" —"),
            "debit": 0.0,
            "credit": float(p["paid_amount"] or 0),
        })
    rows.sort(key=lambda r: (r["date"], r["ref"]))

    # Running balance.
    running = opening_balance
    for r in rows:
        running = running + r["debit"] - r["credit"]
        r["balance"] = running
    closing = running

    company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
    currency = cust.default_currency or frappe.db.get_value("Company", company, "default_currency") or ""

    def fmt(x: float) -> str:
        return f"{x:,.2f}"

    inv_rows_html = "".join(
        f"<tr><td>{r['date']}</td><td>{r['ref']}</td><td>{r['desc']}</td>"
        f"<td style='text-align:right'>{fmt(r['debit']) if r['debit'] else ''}</td>"
        f"<td style='text-align:right'>{fmt(r['credit']) if r['credit'] else ''}</td>"
        f"<td style='text-align:right'>{fmt(r['balance'])}</td></tr>"
        for r in rows
    )
    if not rows:
        inv_rows_html = "<tr><td colspan='6' style='text-align:center;color:#888;padding:1rem'>No transactions in this period.</td></tr>"

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Statement — {cust.customer_name}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; padding: 2rem; color: #111; }}
  h1 {{ font-size: 1.3rem; margin: 0 0 0.2rem; }}
  .meta {{ color: #555; font-size: 0.9rem; margin-bottom: 1rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
  th, td {{ padding: 0.4rem 0.5rem; border-bottom: 1px solid #ddd; }}
  th {{ background: #f5f5f5; text-align: left; }}
  tfoot td {{ font-weight: 700; border-top: 2px solid #111; border-bottom: none; }}
  .opening {{ color: #555; font-style: italic; }}
  @media print {{ body {{ padding: 1rem; }} .no-print {{ display: none; }} }}
  .no-print {{ text-align: right; margin-bottom: 1rem; }}
  .no-print button {{ padding: 0.4rem 0.9rem; border-radius: 6px; border: 1px solid #2563eb; background: #2563eb; color: white; cursor: pointer; }}
</style></head>
<body>
  <div class="no-print"><button onclick="window.print()">Print</button></div>
  <h1>{cust.customer_name} — Statement</h1>
  <div class="meta">
    Period: <strong>{from_date}</strong> to <strong>{to_date}</strong><br/>
    Company: {company} · Currency: {currency}<br/>
    {f'Tax ID: {cust.tax_id}<br/>' if cust.tax_id else ''}
    {f'Mobile: {cust.mobile_no}<br/>' if cust.mobile_no else ''}
  </div>
  <table>
    <thead>
      <tr><th>Date</th><th>Reference</th><th>Description</th>
          <th style="text-align:right">Debit</th>
          <th style="text-align:right">Credit</th>
          <th style="text-align:right">Balance</th></tr>
    </thead>
    <tbody>
      <tr class="opening"><td colspan="5">Opening balance</td>
          <td style="text-align:right">{fmt(opening_balance)}</td></tr>
      {inv_rows_html}
    </tbody>
    <tfoot>
      <tr><td colspan="5" style="text-align:right">Closing balance</td>
          <td style="text-align:right">{fmt(closing)}</td></tr>
    </tfoot>
  </table>
</body></html>"""

    frappe.local.response.type = "download"
    frappe.local.response.filename = f"statement-{name}.html"
    frappe.local.response.filecontent = html.encode("utf-8")
    frappe.local.response.content_type = "text/html"
    frappe.local.response.display_content_as = "inline"


@frappe.whitelist(methods=["GET"])
def summary(customer: str) -> dict:
    """Aggregates for the customer detail tile strip."""
    outstanding = frappe.db.sql(
        """
        SELECT COALESCE(SUM(outstanding_amount), 0)
        FROM `tabSales Invoice`
        WHERE customer = %s AND docstatus = 1
        """,
        (customer,),
    )[0][0] or 0
    last_invoice = frappe.db.get_value(
        "Sales Invoice", {"customer": customer, "docstatus": 1},
        ["name", "grand_total", "posting_date"],
        order_by="posting_date desc",
        as_dict=True,
    )
    if last_invoice:
        last_invoice["posting_date"] = naive_site_to_utc_iso(last_invoice.get("posting_date"))
    return {
        "outstanding": float(outstanding or 0),
        "last_invoice": last_invoice,
    }
