// apps/vansale/vansale/sf_trading/doctype/payment_automation_settings/payment_automation_settings.js
// Payment Automation Settings: scope the pickers, spell out what the run will do, and let
// it be tried safely (dry run) before it is trusted.

frappe.ui.form.on("Payment Automation Settings", {
	setup(frm) {
		frm.set_query("bank_account", () => ({
			filters: { company: frm.doc.company, is_company_account: 1 },
		}));
		frm.set_query("cost_center", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
		frm.set_query("branch", () => ({ filters: {} }));
	},

	refresh(frm) {
		frm.trigger("show_plan");

		if (frm.is_new()) return;

		frm.add_custom_button(__("Dry Run"), () => frm.trigger("run", 1));
		frm.add_custom_button(__("Run Now"), () => {
			frappe.confirm(
				__("Run this configuration now? It ignores the schedule window and does real work up to step {0}.", [
					frm.doc.__step || "1",
				]),
				() => frm.trigger("run", 0)
			);
		}).addClass("btn-primary");

		if (frm.doc.last_execution) {
			frm.dashboard.set_headline(
				__("Last run: {0}", [frappe.datetime.str_to_user(frm.doc.last_execution)])
			);
		}
	},

	run(frm, dry) {
		frappe.call({
			method: "vansale.sf_trading.api.payment_automation.run_now",
			args: { settings_name: frm.doc.name, dry_run: dry ? 1 : 0 },
			freeze: true,
			freeze_message: dry ? __("Working out what would happen…") : __("Running…"),
			callback(r) {
				const s = r.message;
				if (!s) return;
				if (s.skipped) {
					frappe.msgprint({ message: s.reason, indicator: "orange" });
					return;
				}

				const list = (items, render) =>
					items && items.length
						? `<ul>${items.map(render).join("")}</ul>`
						: `<p class="text-muted">${__("None")}</p>`;

				frappe.msgprint({
					title: s.dry_run ? __("Dry Run Result") : __("Run Result"),
					indicator: (s.errors || []).length ? "orange" : "green",
					message: `
						<p>${__("Advices")}: <b>${(s.advices || []).length}</b> ·
						   ${__("submitted")}: ${(s.submitted_advices || []).length} ·
						   ${__("Payment Entries")}: ${(s.payment_entries || []).length} ·
						   ${__("submitted")}: ${(s.submitted_payment_entries || []).length}</p>
						<p>${__("Total")}: <b>${format_currency(s.total_amount || 0)}</b></p>
						${list(s.advices, (a) => `<li>${a.advice} — ${a.party} — ${format_currency(a.amount)}</li>`)}
						<p>${__("Skipped")}:</p>
						${list(s.skipped, (x) => `<li>${x.party} — ${x.label || x.reason}</li>`)}
						${
							(s.errors || []).length
								? `<p>${__("Errors")}:</p>${list(s.errors, (e) => `<li class="text-danger">${e}</li>`)}`
								: ""
						}
					`,
				});
				frm.reload_doc();
			},
		});
	},

	show_plan(frm) {
		// say in words how far this configuration goes — checkbox soup hides the risk
		const steps = [
			[frm.doc.auto_create_advice, __("create advices")],
			[frm.doc.auto_submit_advice, __("submit advices")],
			[frm.doc.auto_create_payment_entry, __("create Payment Entries")],
			[frm.doc.auto_submit_payment_entry, __("submit Payment Entries")],
		]
			.filter(([on]) => on)
			.map(([, label]) => label);

		if (!steps.length) {
			frm.dashboard.clear_headline();
			return;
		}

		const days = [
			"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
		]
			.filter((d) => frm.doc["automate_on_" + d])
			.map((d) => __(d.charAt(0).toUpperCase() + d.slice(1, 3)));

		const suffix = frm.doc.dry_run ? ` — ${__("DRY RUN, nothing will be created")}` : "";
		frm.dashboard.set_headline(
			`${frm.doc.enabled ? "" : __("(disabled)") + " "}${__("Will")} ${steps.join(" → ")} ${__(
				"on"
			)} ${days.join(", ") || __("no days")} ${__("at")} ${frm.doc.processing_time || "—"}${suffix}`
		);
	},

	enabled: (frm) => frm.trigger("show_plan"),
	dry_run: (frm) => frm.trigger("show_plan"),
	auto_create_advice: (frm) => frm.trigger("show_plan"),
	auto_submit_advice: (frm) => frm.trigger("show_plan"),
	auto_create_payment_entry: (frm) => frm.trigger("show_plan"),
	auto_submit_payment_entry: (frm) => frm.trigger("show_plan"),
});
