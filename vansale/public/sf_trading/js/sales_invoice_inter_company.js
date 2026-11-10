// sf_trading: Inter Company Branch - filter branches by buying company
frappe.ui.form.on("Sales Invoice", {
	onload: function (frm) {
		frm.set_query("inter_company_branch", function () {
			if (!frm.doc.represents_company) {
				return { filters: { name: "" } };
			}
			return {
				query: "vansale.sf_trading.doctype.inter_company_branch.inter_company_branch.get_branches_for_company",
				filters: { company: frm.doc.represents_company },
			};
		});
	},
});
