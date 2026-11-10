// Currency-based Purchase Tax Template — live form feedback.
// The rule itself is enforced server-side in sf_trading/purchase_tax_template.py
// (before_validate), so this only keeps the form display in sync.

(function () {
	const DOCTYPES = [
		"Supplier Quotation",
		"Purchase Order",
		"Purchase Receipt",
		"Purchase Invoice",
	];

	function apply_template_by_currency(frm) {
		if (!frm.doc.company || !frm.doc.currency || frm.doc.docstatus !== 0) return;
		frappe.call({
			method: "vansale.sf_trading.purchase_tax_template.get_expected_template",
			args: { company: frm.doc.company, currency: frm.doc.currency, supplier: frm.doc.supplier },
			callback: (r) => {
				const template = r.message;
				if (template && frm.doc.taxes_and_charges !== template) {
					frm.set_value("taxes_and_charges", template);
				}
			},
		});
	}

	// ERPNext's core get_party_details passes the document's *current* currency
	// as a fallback to the backend, so when the newly selected supplier has no
	// default_currency, the currency field is left unchanged instead of
	// resetting to the company's currency (erpnext/accounts/party.py: `currency =
	// party.get("default_currency") or currency or get_company_currency(company)`).
	// Correct that here before re-checking the tax template.
	function on_supplier_change(frm) {
		if (!frm.doc.supplier || !frm.doc.company || frm.doc.docstatus !== 0) {
			apply_template_by_currency(frm);
			return;
		}

		// Documents populated by mapping from another doc (e.g. Purchase Order ->
		// Purchase Invoice via "Get Items From") already carry the deliberately
		// chosen currency of the source document. Re-running the no-default-
		// currency correction here would stomp that back to the company currency.
		// ERPNext core guards its own currency()/company() handlers in
		// controllers/transaction.js the same way, for the same reason.
		if (frm.doc.__onload && frm.doc.__onload.load_after_mapping) {
			apply_template_by_currency(frm);
			return;
		}

		Promise.all([
			frappe.db.get_value("Supplier", frm.doc.supplier, ["default_currency", "tax_id"]),
			frappe.db.get_value("Company", frm.doc.company, "default_currency"),
		]).then(([supplier_r, company_r]) => {
			const supplier_currency = supplier_r.message && supplier_r.message.default_currency;
			const supplier_tax_id = supplier_r.message && supplier_r.message.tax_id;
			const company_currency = company_r.message && company_r.message.default_currency;

			const finish = () => {
				// The no-tax-id template only applies for same-currency (local) purchases.
				const is_local = company_currency && frm.doc.currency === company_currency;
				if (is_local && !supplier_tax_id) {
					frappe.msgprint(
						__("{0} has no Tax ID, so this purchase will be taxed at 0% VAT.", [
							frappe.utils.escape_html(frm.doc.supplier),
						])
					);
				}
				apply_template_by_currency(frm);
			};

			if (!supplier_currency && company_currency && frm.doc.currency !== company_currency) {
				frm.set_value("currency", company_currency).then(finish);
			} else {
				finish();
			}
		});
	}

	DOCTYPES.forEach((dt) => {
		frappe.ui.form.on(dt, {
			currency: apply_template_by_currency,
			company: apply_template_by_currency,
			supplier: on_supplier_change,
			// Catches the case where the supplier's Tax ID was added in another
			// tab while this document was still open — re-checked when the form
			// regains focus/reloads. The authoritative fix is server-side on
			// save regardless.
			refresh: apply_template_by_currency,
		});
	});
})();
