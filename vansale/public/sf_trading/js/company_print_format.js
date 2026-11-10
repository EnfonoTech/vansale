frappe.provide("sf_trading");

// ─── Company form: filter Print Format by Document Type in child table ───────

frappe.ui.form.on("Company", {
	setup: function (frm) {
		frm.set_query("print_format", "custom_print_formats", function (doc, cdt, cdn) {
			var row = frappe.get_doc(cdt, cdn);
			return { filters: { doc_type: row.document_type || "" } };
		});
	},
});

// ─── Shared lookup (frappe.xcall resolves with r.message directly) ────────────

sf_trading.get_company_print_format = function (company, doctype, callback) {
	if (!company) {
		callback(null);
		return;
	}
	frappe
		.xcall("vansale.sf_trading.api.company_print_format.get_company_print_format", {
			company: company,
			document_type: doctype,
		})
		.then(function (result) {
			callback(result || null);
		})
		.catch(function () {
			callback(null);
		});
};

// ─── Patches ─────────────────────────────────────────────────────────────────

$(document).ready(function () {

	// ── Patch 1: Form.prototype.print_doc ─────────────────────────────────────
	// Fetch company format and stash it on frm._sf_company_format before routing.
	// We deliberately do NOT touch frm.meta.default_print_format so that the
	// auto-print-after-submit path (which reads that field) keeps using the
	// doctype-level default unchanged.

	if (frappe.ui && frappe.ui.form && frappe.ui.form.Form) {
		var _orig_print_doc = frappe.ui.form.Form.prototype.print_doc;

		if (!_orig_print_doc._sf_patched) {
			frappe.ui.form.Form.prototype.print_doc = function () {
				var frm = this;
				if (!frm.doc || !frm.doc.company) {
					return _orig_print_doc.call(frm);
				}
				sf_trading.get_company_print_format(
					frm.doc.company,
					frm.doctype,
					function (format) {
						frm._sf_company_format = format || null;
						_orig_print_doc.call(frm);
					}
				);
			};
			frappe.ui.form.Form.prototype.print_doc._sf_patched = true;
		}
	}

	// ── Patch 2: PrintView.set_default_print_format ───────────────────────────
	// We need this patch in place BEFORE any PrintView instance is created
	// (i.e. before print.js's on_page_load runs).
	//
	// print.js is lazy-loaded — it assigns frappe.ui.form.PrintView = class {...}
	// when the /print page is first visited. We intercept that exact assignment
	// via Object.defineProperty so the prototype is patched immediately, before
	// on_page_load creates the first instance.

	function sf_patch_print_view(PrintView) {
		if (!PrintView || PrintView.prototype._sf_patched) return;

		var _orig_set_format = PrintView.prototype.set_default_print_format;

		PrintView.prototype.set_default_print_format = function () {
			var frm = this.frm;
			var format = frm && frm._sf_company_format;
			if (format) {
				this.print_format_selector.val(format);
				return;
			}
			return _orig_set_format.call(this);
		};

		PrintView.prototype._sf_patched = true;
	}

	if (frappe.ui && frappe.ui.form) {
		if (frappe.ui.form.PrintView) {
			// Already loaded (cached page)
			sf_patch_print_view(frappe.ui.form.PrintView);
		} else {
			// Intercept the assignment frappe.ui.form.PrintView = class {...}
			// This fires inside print.js execution, before on_page_load creates
			// any instance, so the patched prototype is ready from the very first use.
			var _stored_pv;
			try {
				Object.defineProperty(frappe.ui.form, "PrintView", {
					configurable: true,
					enumerable: true,
					get: function () { return _stored_pv; },
					set: function (cls) {
						_stored_pv = cls;
						sf_patch_print_view(cls);
						// Replace interceptor with a plain writable property
						try {
							Object.defineProperty(frappe.ui.form, "PrintView", {
								value: cls, writable: true,
								configurable: true, enumerable: true,
							});
						} catch (_) { /* getter above still returns cls */ }
					},
				});
			} catch (_) {
				// Fallback: patch via page-change (works from the second visit onwards;
				// first visit relies on the meta set by the Form.print_doc patch above)
				$(document).on("page-change", function () {
					if (frappe.ui.form.PrintView) {
						sf_patch_print_view(frappe.ui.form.PrintView);
					}
				});
			}
		}
	}
});
