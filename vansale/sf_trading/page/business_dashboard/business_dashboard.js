// apps/vansale/vansale/sf_trading/page/business_dashboard/business_dashboard.js
//
// One call fills the whole page (vansale.sf_trading.api.business_dashboard.get_dashboard) and every
// panel is drawn from that one payload, so nothing on screen can disagree with anything else.
// Changing a filter re-fetches; nothing is computed twice in the browser.
//
// Money figures come from the ledger, so they tie to the Trial Balance. See the API module for
// why they are not summed from payment documents.

frappe.pages["business-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Business Dashboard"),
		single_column: true,
	});
	new BusinessDashboard(page);
};

const FMT = (v, currency) =>
	format_currency(flt(v), currency || frappe.boot.sysdefaults.currency);

class BusinessDashboard {
	constructor(page) {
		this.page = page;
		this.charts = {};
		this.filters = {};
		// Shell first: add_field fires its change handler while the field is being created,
		// and refresh() writes into the shell. Built the other way round the first refresh
		// runs against an undefined body.
		this._build_shell();
		this._build_filters();
		this._ready = true;
		this.refresh();
	}

	// ── filters ───────────────────────────────────────────────────────────────
	_build_filters() {
		const today = frappe.datetime.get_today();

		this.filters.company = this.page.add_field({
			fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			change: () => this._queue_refresh(),
		});
		this.filters.from_date = this.page.add_field({
			fieldname: "from_date", label: __("From"), fieldtype: "Date",
			default: frappe.datetime.add_months(today, -6),
			change: () => this._queue_refresh(),
		});
		this.filters.to_date = this.page.add_field({
			fieldname: "to_date", label: __("To"), fieldtype: "Date", default: today,
			change: () => this._queue_refresh(),
		});
		this.filters.granularity = this.page.add_field({
			fieldname: "granularity", label: __("View by"), fieldtype: "Select",
			options: ["Daily", "Weekly", "Monthly"].join("\n"), default: "Monthly",
			change: () => this._queue_refresh(),
		});
		this.filters.cost_center = this.page.add_field({
			fieldname: "cost_center", label: __("Cost Center"), fieldtype: "Link",
			options: "Cost Center",
			get_query: () => ({ filters: { company: this._val("company"), is_group: 0 } }),
			change: () => this._queue_refresh(),
		});
		this.filters.mode_of_payment = this.page.add_field({
			fieldname: "mode_of_payment", label: __("Payment Mode"), fieldtype: "Link",
			options: "Mode of Payment",
			change: () => this._queue_refresh(),
		});

		this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.page.add_menu_item(__("Cash Flow report"), () =>
			frappe.set_route("query-report", "Cash Flow Money In vs Money Out")
		);
	}

	// Six filters each fire change while being created, and every change asked the server for
	// the whole dashboard - fifteen identical requests on load. Coalesce them.
	_queue_refresh() {
		if (!this._ready) return;
		clearTimeout(this._timer);
		this._timer = setTimeout(() => this.refresh(), 150);
	}

	_val(name) {
		const f = this.filters[name];
		return f ? f.get_value() : null;
	}

	_build_shell() {
		this.$body = $(`
			<div class="sfbd">
				<div class="sfbd-loading text-muted">${__("Loading…")}</div>
				<div class="sfbd-content" style="display:none">
					<div class="sfbd-section sfbd-money"></div>
					<div class="sfbd-section sfbd-kpi"></div>
					<div class="sfbd-grid">
						<div class="sfbd-card sfbd-span2"><h6>${__("Sales, Expenses & Profit")}</h6><div class="sfbd-chart" id="sfbd-trend"></div></div>
						<div class="sfbd-card"><h6>${__("Expenses by Category")}</h6><div class="sfbd-chart" id="sfbd-expense"></div></div>
					</div>
					<div class="sfbd-grid">
						<div class="sfbd-card sfbd-span2"><h6>${__("Cash Flow — Money In vs Money Out")}</h6><div class="sfbd-chart" id="sfbd-cash"></div></div>
						<div class="sfbd-card"><h6>${__("Running Balance")}</h6><div class="sfbd-chart" id="sfbd-running"></div></div>
					</div>
					<div class="sfbd-grid">
						<div class="sfbd-card"><h6>${__("Owed to us")}</h6><div class="sfbd-recv"></div></div>
						<div class="sfbd-card"><h6>${__("We owe")}</h6><div class="sfbd-pay"></div></div>
						<div class="sfbd-card"><h6>${__("Insights")}</h6><div class="sfbd-insights"></div></div>
					</div>
					<div class="sfbd-card sfbd-quality"></div>
					<div class="sfbd-foot text-muted"></div>
				</div>
			</div>
		`).appendTo(this.page.main);
		this._inject_css();
	}

	// ── load ──────────────────────────────────────────────────────────────────
	refresh() {
		const $c = this.$body.find(".sfbd-content");
		const $l = this.$body.find(".sfbd-loading");
		$l.show().text(__("Loading…"));

		frappe.call({
			method: "vansale.sf_trading.api.business_dashboard.get_dashboard",
			args: {
				company: this._val("company"),
				from_date: this._val("from_date"),
				to_date: this._val("to_date"),
				granularity: this._val("granularity") || "Monthly",
				cost_center: this._val("cost_center"),
				mode_of_payment: this._val("mode_of_payment"),
			},
			callback: (r) => {
				if (!r || !r.message) {
					$l.text(__("No data returned."));
					return;
				}
				this.data = r.message;
				try {
					this._render();
					$l.hide();
					$c.show();
				} catch (e) {
					// Better a visible failure than a page that says Loading for ever.
					console.error("Business Dashboard render failed", e);
					$c.hide();
					$l.show().html(
						`<div class="text-danger">${__("The dashboard loaded its data but could not draw it.")}</div>
						 <div class="text-muted small">${frappe.utils.escape_html(String(e && e.message || e))}</div>`
					);
				}
			},
			error: () => $l.text(__("Could not load the dashboard.")),
		});
	}

	_render() {
		const d = this.data;
		const cur = d.meta.currency;
		this._money(d.money, cur);
		this._kpis(d.kpi, cur);
		this._trend(d.trend);
		this._expenses(d.expenses);
		this._cashflow(d.cashflow);
		this._outstanding(d.outstanding, cur);
		this._insights(d.insights, cur);
		this._quality(d.quality, cur);
		this.$body.find(".sfbd-foot").text(
			__("{0} · {1} to {2} · generated {3}", [
				d.meta.company, d.meta.from_date, d.meta.to_date, d.meta.generated_on])
		);
	}

	// ── money position: the headline ──────────────────────────────────────────
	_money(m, cur) {
		const warn = (m.negative || []).length
			? `<div class="sfbd-warn">${__("{0} account(s) are overdrawn", [m.negative.length])}: ${
				m.negative.map((a) => frappe.utils.escape_html(a.label)).join(", ")}</div>`
			: "";
		const accounts = (m.accounts || []).map((a) => `
			<div class="sfbd-acct ${flt(a.balance) < 0 ? "neg" : ""}">
				<span class="sfbd-acct-name">${frappe.utils.escape_html(a.label)}</span>
				<span class="sfbd-acct-type">${a.type}</span>
				<span class="sfbd-acct-bal">${FMT(a.balance, cur)}</span>
			</div>`).join("");

		this.$body.find(".sfbd-money").html(`
			<div class="sfbd-hero">
				<div class="sfbd-hero-main">
					<div class="sfbd-hero-label">${__("Total Available Money")}</div>
					<div class="sfbd-hero-value">${FMT(m.total, cur)}</div>
					<div class="sfbd-hero-split">
						<span>${__("Cash in Hand")} <b>${FMT(m.cash, cur)}</b></span>
						<span>${__("Bank")} <b>${FMT(m.bank, cur)}</b></span>
					</div>
				</div>
				<div class="sfbd-hero-accounts">${accounts}</div>
			</div>${warn}`);
	}

	_kpis(k, cur) {
		const growth = k.sales_growth_pct === null || k.sales_growth_pct === undefined
			? ""
			: `<span class="sfbd-delta ${k.sales_growth_pct >= 0 ? "up" : "down"}">${
				k.sales_growth_pct >= 0 ? "▲" : "▼"} ${Math.abs(k.sales_growth_pct)}% ${
				__("vs last year")}</span>`;
		const card = (label, value, cls, extra) => `
			<div class="sfbd-kpi-card ${cls}">
				<div class="sfbd-kpi-label">${label}</div>
				<div class="sfbd-kpi-value">${value}</div>
				<div class="sfbd-kpi-extra">${extra || ""}</div>
			</div>`;

		this.$body.find(".sfbd-kpi").html(
			card(__("Total Sales"), FMT(k.sales, cur), "blue", growth) +
			card(__("Total Expenses"), FMT(k.expenses, cur), "orange", "") +
			card(__("Profit"), FMT(k.profit, cur), k.profit >= 0 ? "green" : "red",
				`${k.margin_pct}% ${__("margin")}`)
		);
	}

	// ── charts ────────────────────────────────────────────────────────────────
	_chart(id, opts) {
		const el = this.$body.find("#" + id).get(0);
		if (!el) return;
		if (typeof frappe.Chart === "undefined") {
			$(el).html(`<p class="text-muted">${__("Charts are unavailable on this page.")}</p>`);
			return;
		}
		if (this.charts[id]) {
			this.charts[id].destroy && this.charts[id].destroy();
			$(el).empty();
		}
		this.charts[id] = new frappe.Chart(el, opts);
	}

	_trend(rows) {
		if (!rows || !rows.length) {
			this.$body.find("#sfbd-trend").html(`<p class="text-muted">${__("No activity in this period.")}</p>`);
			return;
		}
		this._chart("sfbd-trend", {
			data: {
				labels: rows.map((r) => r.bucket),
				datasets: [
					{ name: __("Sales"), values: rows.map((r) => flt(r.sales)), chartType: "bar" },
					{ name: __("Expenses"), values: rows.map((r) => flt(r.expenses)), chartType: "bar" },
					{ name: __("Profit"), values: rows.map((r) => flt(r.profit)), chartType: "line" },
				],
			},
			type: "axis-mixed",
			height: 260,
			colors: ["#1565c0", "#ef6c00", "#2e7d32"],
			axisOptions: { xIsSeries: 1 },
			barOptions: { spaceRatio: 0.3 },
		});
	}

	_expenses(e) {
		const cats = (e && e.categories) || [];
		if (!cats.length) {
			this.$body.find("#sfbd-expense").html(`<p class="text-muted">${__("No expenses.")}</p>`);
			return;
		}
		this._chart("sfbd-expense", {
			data: {
				labels: cats.map((c) => c.label),
				datasets: [{ name: __("Expenses"), values: cats.map((c) => flt(c.amount)) }],
			},
			type: "donut",
			height: 260,
			colors: ["#1565c0", "#ef6c00", "#2e7d32", "#6a1b9a", "#c62828", "#00838f",
				"#f9a825", "#4527a0", "#ad1457", "#2e7d32", "#37474f", "#5d4037"],
		});
	}

	_cashflow(c) {
		const rows = (c && c.rows) || [];
		if (!rows.length) {
			this.$body.find("#sfbd-cash").html(`<p class="text-muted">${c && c.note ? c.note : __("No money moved in this period.")}</p>`);
			this.$body.find("#sfbd-running").empty();
			return;
		}
		this._chart("sfbd-cash", {
			data: {
				labels: rows.map((r) => r.bucket),
				datasets: [
					{ name: __("Money In"), values: rows.map((r) => flt(r.money_in)) },
					{ name: __("Money Out"), values: rows.map((r) => flt(r.money_out)) },
				],
			},
			type: "bar",
			height: 260,
			colors: ["#2e7d32", "#c62828"],
			axisOptions: { xIsSeries: 1 },
		});
		this._chart("sfbd-running", {
			data: {
				labels: rows.map((r) => r.bucket),
				datasets: [{ name: __("Running Balance"), values: rows.map((r) => flt(r.running)) }],
			},
			type: "line",
			height: 260,
			colors: ["#1565c0"],
			lineOptions: { regionFill: 1, hideDots: 1 },
			axisOptions: { xIsSeries: 1 },
		});
	}

	// ── lists ─────────────────────────────────────────────────────────────────
	_outstanding(o, cur) {
		const line = (label, value, sub) =>
			`<div class="sfbd-line"><span>${label}</span><b>${value}</b>${
				sub ? `<small class="text-muted">${sub}</small>` : ""}</div>`;
		const docs = (rows, party, dt) => (rows || []).map((r) => `
			<div class="sfbd-line small">
				<a href="/app/${frappe.router.slug(dt)}/${encodeURIComponent(r.name)}" target="_blank">${
					frappe.utils.escape_html(r[party] || r.name)}</a>
				<b>${FMT(r.outstanding_amount, cur)}</b>
			</div>`).join("");

		this.$body.find(".sfbd-recv").html(
			line(__("Receivables"), FMT(o.receivable, cur), __("{0} invoices", [o.receivable_count])) +
			line(__("Overdue"), FMT(o.receivable_overdue, cur),
				__("{0} invoices", [o.receivable_overdue_count])) +
			`<div class="sfbd-sub">${__("Largest")}</div>` + docs(o.top_receivable, "customer", "Sales Invoice")
		);
		this.$body.find(".sfbd-pay").html(
			line(__("Payables"), FMT(o.payable, cur), __("{0} invoices", [o.payable_count])) +
			line(__("Overdue"), FMT(o.payable_overdue, cur),
				__("{0} invoices", [o.payable_overdue_count])) +
			`<div class="sfbd-sub">${__("Largest")}</div>` + docs(o.top_payable, "supplier", "Purchase Invoice")
		);
	}

	_insights(i, cur) {
		let html = "";
		if (i.best_month) {
			html += `<div class="sfbd-line"><span>${__("Best sales month")}</span><b>${
				i.best_month.bucket} · ${FMT(i.best_month.sales, cur)}</b></div>`;
		}
		if ((i.top_expenses || []).length) {
			html += `<div class="sfbd-sub">${__("Top expenses")}</div>`;
			html += i.top_expenses.map((e) => `<div class="sfbd-line small"><span>${
				frappe.utils.escape_html(e.account.split(" - ")[1] || e.account)}</span><b>${
				FMT(e.amount, cur)}</b></div>`).join("");
		}
		if ((i.biggest_sales || []).length) {
			html += `<div class="sfbd-sub">${__("Biggest sales")}</div>`;
			html += i.biggest_sales.map((s) => `<div class="sfbd-line small">
				<a href="/app/sales-invoice/${encodeURIComponent(s.name)}" target="_blank">${
					frappe.utils.escape_html(s.customer || s.name)}</a>
				<b>${FMT(s.base_grand_total, cur)}</b></div>`).join("");
		}
		this.$body.find(".sfbd-insights").html(html || `<p class="text-muted">${__("Nothing to report.")}</p>`);
	}

	// ── data quality: reported, never corrected ───────────────────────────────
	_quality(q, cur) {
		const findings = (q && q.findings) || [];
		if (!findings.length) {
			this.$body.find(".sfbd-quality").html(
				`<h6>${__("Data Quality")}</h6><p class="text-muted">${
					__("Nothing unusual found in this period.")}</p>`);
			return;
		}
		const rows = findings.map((f) => `
			<div class="sfbd-flag sfbd-flag-${f.severity}">
				<div class="sfbd-flag-head">
					<b>${frappe.utils.escape_html(f.title)}</b>
					<span class="sfbd-flag-count">${f.count}${
						f.amount ? " · " + FMT(f.amount, cur) : ""}</span>
				</div>
				<div class="sfbd-flag-detail text-muted">${frappe.utils.escape_html(f.detail || "")}</div>
				${(f.rows || []).length
					? `<div class="sfbd-flag-rows">${f.rows.map((r) =>
						`<div class="small"><span>${frappe.utils.escape_html(r.label)}</span>
						 <code>${frappe.utils.escape_html(r.value)}</code></div>`).join("")}</div>`
					: ""}
			</div>`).join("");

		this.$body.find(".sfbd-quality").html(`
			<h6>${__("Data Quality")}</h6>
			<p class="text-muted small">${__(
				"Flagged for a person to judge. Nothing here has been changed — these are posted "
				+ "accounting entries, and correcting them anywhere but at source would put this "
				+ "page out of step with the ledger.")}</p>
			${rows}`);
	}

	_inject_css() {
		if (document.getElementById("sfbd-style")) return;
		$(`<style id="sfbd-style">
			.sfbd { padding: 4px 0 40px; }
			.sfbd h6 { font-size: 12px; text-transform: uppercase; letter-spacing: .4px;
				color: var(--text-muted); margin-bottom: 10px; }
			.sfbd-section { margin-bottom: 16px; }
			.sfbd-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px;
				margin-bottom: 16px; }
			.sfbd-span2 { grid-column: span 2; }
			.sfbd-card { background: var(--card-bg); border: 1px solid var(--border-color);
				border-radius: 10px; padding: 14px 16px; }

			.sfbd-hero { display: flex; gap: 18px; align-items: stretch;
				background: linear-gradient(135deg, #0f4c81 0%, #1565c0 55%, #1f8a70 100%);
				color: #fff; border-radius: 12px; padding: 18px 20px; }
			.sfbd-hero-main { flex: 1 1 40%; }
			.sfbd-hero-label { font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
				opacity: .85; }
			.sfbd-hero-value { font-size: 34px; font-weight: 700; line-height: 1.15; margin: 2px 0 6px; }
			.sfbd-hero-split span { margin-right: 18px; font-size: 12px; opacity: .95; }
			.sfbd-hero-accounts { flex: 1 1 60%; display: grid;
				grid-template-columns: repeat(2, 1fr); gap: 4px 14px; align-content: center; }
			.sfbd-acct { display: flex; align-items: baseline; gap: 8px; font-size: 11.5px;
				border-bottom: 1px solid rgba(255,255,255,.18); padding: 3px 0; }
			.sfbd-acct-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
			.sfbd-acct-type { opacity: .7; font-size: 9.5px; text-transform: uppercase; }
			.sfbd-acct-bal { font-weight: 600; }
			.sfbd-acct.neg .sfbd-acct-bal { color: #ffcdd2; }
			.sfbd-warn { margin-top: 8px; padding: 8px 12px; border-radius: 8px;
				background: var(--red-50); color: var(--red-700); font-size: 12px; }

			.sfbd-kpi { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
			.sfbd-kpi-card { border-radius: 10px; padding: 14px 16px; color: #fff; }
			.sfbd-kpi-card.blue { background: linear-gradient(135deg,#1565c0,#42a5f5); }
			.sfbd-kpi-card.orange { background: linear-gradient(135deg,#ef6c00,#ffa726); }
			.sfbd-kpi-card.green { background: linear-gradient(135deg,#2e7d32,#66bb6a); }
			.sfbd-kpi-card.red { background: linear-gradient(135deg,#c62828,#ef5350); }
			.sfbd-kpi-label { font-size: 11px; text-transform: uppercase; letter-spacing: .6px;
				opacity: .9; }
			.sfbd-kpi-value { font-size: 25px; font-weight: 700; margin: 3px 0; }
			.sfbd-kpi-extra { font-size: 11px; opacity: .95; min-height: 15px; }
			.sfbd-delta.up::before, .sfbd-delta.down::before { content: ""; }

			.sfbd-line { display: flex; align-items: baseline; gap: 8px; padding: 4px 0;
				border-bottom: 1px solid var(--border-color); font-size: 12.5px; }
			.sfbd-line span, .sfbd-line a { flex: 1; overflow: hidden;
				text-overflow: ellipsis; white-space: nowrap; }
			.sfbd-line b { font-variant-numeric: tabular-nums; }
			.sfbd-line.small { font-size: 11.5px; border-bottom: 0; padding: 2px 0; }
			.sfbd-sub { margin-top: 10px; font-size: 10px; text-transform: uppercase;
				letter-spacing: .5px; color: var(--text-muted); }

			.sfbd-flag { border-left: 3px solid var(--gray-300); padding: 8px 12px;
				margin-bottom: 8px; background: var(--bg-light-gray); border-radius: 0 8px 8px 0; }
			.sfbd-flag-danger { border-left-color: var(--red-500); }
			.sfbd-flag-warning { border-left-color: var(--orange-500); }
			.sfbd-flag-info { border-left-color: var(--blue-400); }
			.sfbd-flag-head { display: flex; justify-content: space-between; font-size: 12.5px; }
			.sfbd-flag-count { font-variant-numeric: tabular-nums; }
			.sfbd-flag-detail { font-size: 11.5px; margin-top: 2px; }
			.sfbd-flag-rows { margin-top: 6px; }
			.sfbd-flag-rows div { display: flex; gap: 10px; justify-content: space-between; }

			.sfbd-foot { margin-top: 14px; font-size: 11px; text-align: right; }

			@media (max-width: 1100px) {
				.sfbd-grid, .sfbd-kpi { grid-template-columns: 1fr; }
				.sfbd-span2 { grid-column: auto; }
				.sfbd-hero { flex-direction: column; }
				.sfbd-hero-accounts { grid-template-columns: 1fr; }
			}
		</style>`).appendTo(document.head);
	}
}
