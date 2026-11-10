"""Open-item gate on the Period Closing Voucher.

A period should not close while documents dated inside it still wait for
their counterpart — an invoice with no delivery, a delivery with no invoice,
a receipt with no bill, a bill with no receipt. Those rows are exactly what
the four open item reports print (vansale.sf_trading.open_items), so the gate reuses
that engine rather than judging afresh.

Population vs clearing dates are deliberately different:

    counted:  rows whose document is dated ON OR BEFORE the period end
    cleared:  by any counterpart submitted up to TODAY, whatever its date

so a delivery raised this morning against a March invoice unblocks a March
closing immediately — the accountant clears items, refreshes the draft
voucher, and watches the list shrink. Cutting the clearing at period end
instead would leave the voucher permanently blocked by items that are, in
fact, resolved.

Blocking is per company and OFF by default (`Block Period Closing on Open Items`
on Company). A site that already carries a long tail of open items — an aged
GRNI backlog, say — would otherwise find its first period close refused with no
way through, so the census is shown to everybody and only enforced where
somebody asked for it.

Wired in hooks.py:
    doc_events["Period Closing Voucher"]["before_submit"] -> validate_open_items
    doctype_js["Period Closing Voucher"] -> public/js/period_closing_voucher.js
    after_migrate -> ensure_custom_fields
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, flt, fmt_money, getdate

from vansale.sf_trading.open_items import (
	billed_items_pending_receipt,
	delivered_items_pending_billing,
	invoiced_items_to_be_delivered,
	received_items_pending_billing,
)

FLOWS = [
	("Invoiced Items To Be Delivered", invoiced_items_to_be_delivered),
	("Delivered Items Pending Billing", delivered_items_pending_billing),
	("Received Items Pending Billing", received_items_pending_billing),
	("Billed Items Pending Receipt", billed_items_pending_receipt),
]

ENFORCE_FIELD = "custom_block_period_closing_on_open_items"


def is_gate_enforced(company: str) -> bool:
	"""Whether this company asked for open items to block a period close.

	Reads through the cache and tolerates the field being absent — on a bench
	that has the code but has not run the provisioning yet the answer is a
	plain no, which is the safe direction for a gate.
	"""
	if not company:
		return False

	return bool(cint(frappe.get_cached_value("Company", company, ENFORCE_FIELD)))


@frappe.whitelist()
def pending_open_items(company: str, period_end_date: str):
	"""Per-flow census of items dated in or before the period, still open now.

	Serves the form view and the submit gate alike, so what the accountant
	sees on the draft is byte-for-byte what the gate will judge. `enforced`
	rides along so the form can say whether the list blocks or merely informs.
	"""
	frappe.has_permission("Period Closing Voucher", "read", throw=True)

	if not (company and period_end_date):
		frappe.throw(_("Company and Period End Date are required"))

	period_end = getdate(period_end_date)
	filters = frappe._dict({"company": company})  # as_on defaults to today

	summary = []
	for report_name, flow in FLOWS:
		rows = [row for row in flow(filters) if getdate(row.posting_date) <= period_end]
		summary.append(
			{
				"report": report_name,
				"documents": len({row.document for row in rows}),
				"items": len(rows),
				"qty": flt(sum(row.pending_qty for row in rows), 3),
				"value": flt(sum(row.pending_amount for row in rows), 2),
			}
		)

	return {"enforced": is_gate_enforced(company), "rows": summary}


def validate_open_items(doc, method=None):
	"""Period Closing Voucher.before_submit: refuse while open items remain."""
	if not is_gate_enforced(doc.company):
		return

	census = pending_open_items(doc.company, doc.period_end_date)
	pending = [row for row in census["rows"] if row["items"]]

	if not pending:
		return

	currency = frappe.get_cached_value("Company", doc.company, "default_currency")
	lines = []
	for row in pending:
		detail = _("%(documents)s documents, %(items)s items, value %(value)s") % {
			"documents": row["documents"],
			"items": row["items"],
			"value": fmt_money(row["value"], currency=currency),
		}
		lines.append("<li>" + frappe.bold(_(row["report"])) + ": " + detail + "</li>")

	message = _(
		"The period up to %(period_end)s still carries open items — bill, deliver, receive or return them first:"
	) % {"period_end": frappe.bold(frappe.format(getdate(doc.period_end_date), {"fieldtype": "Date"}))}
	message += "<ul>" + "".join(lines) + "</ul>"
	message += _("Each list above is available as a report of the same name.")

	frappe.throw(msg=message, title=_("Open Items Pending"))


def ensure_custom_fields():
	"""after_migrate: the per-company switch that arms the gate.

	Runs after stock_billing_setup, so the anchor field it sits below already
	exists and the accounting switches group together on the Company form.
	"""
	create_custom_fields(
		{
			"Company": [
				{
					"fieldname": ENFORCE_FIELD,
					"label": "Block Period Closing on Open Items",
					"fieldtype": "Check",
					"default": "0",
					"insert_after": "custom_stock_billed_but_not_delivered",
					"description": (
						"If enabled, a Period Closing Voucher cannot be submitted while the period "
						"still carries items waiting to be billed, delivered or received. The list "
						"is shown on the voucher either way."
					),
				}
			]
		},
		ignore_validate=True,
	)
