// Van Customer Assignment — desk-side admin utility.
//
// Picks a driver (User) → resolves their Sales Person from the Vansale
// Configuration mapping and shows it read-only. The admin then builds
// the driver's weekly roster:
//
//   • RIGHT column: the pool of candidate customers (every customer
//     not yet on this driver's roster). Each row has an "Add" button.
//     Clicking Add moves that row to the LEFT column and hides it here.
//
//   • LEFT column: day-wise buckets (Mon..Sun plus "Every day"). The
//     customers added from the right land under the day the admin
//     picks on the row. The bucket view makes it obvious which day is
//     empty or crowded. The admin can change a row's day, remove it,
//     or leave as "Every day" (blank CSV = visit every day).
//
//   • SUBMIT — stages all changes and fires a single bulk call to the
//     server. Nothing is written until Submit is clicked, so mistakes
//     can be rolled back via the "Reset" button without a round-trip.
//
// All mutations go through vansale.api.route whitelisted endpoints so
// permission gating + idempotency stay server-side.

frappe.pages['van-customer-assignment'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Van Customer Assignment'),
		single_column: true,
	});
	new VanCustomerAssignment(page);
};

const DAY_CODES = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const DAY_SHORT = { mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat', sun: 'Sun' };
const DAY_ORDER = Object.fromEntries(DAY_CODES.map((c, i) => [c, i]));

class VanCustomerAssignment {
	constructor(page) {
		this.page = page;
		this.$wrap = $(page.body);
		this.user = null;
		this.sales_person = null;
		// left roster: array of {customer, customer_name, mobile_no, day, _origDay, _origAssigned, _removed}
		//   day: 'every' | 'mon' | ... | 'sun'
		//   _origAssigned: whether this row came from the server (vs newly added here)
		this.roster = [];
		// right pool: array of {customer, customer_name, mobile_no, assigned_to}
		this.pool = [];
		this.pool_filter = '';
		// when 1, backend returns customers already tagged to OTHER
		// sales_persons — UI shows them with "Move here" / reassign button.
		this.include_assigned = 0;
		this.render_scaffold();
		this.bind_controls();
	}

	render_scaffold() {
		this.$wrap.html(`
			<div class="vca-root">
				<div class="vca-picker-card">
					<div class="vca-picker-row">
						<div class="vca-field" data-field="user"></div>
						<div class="vca-sp-display">
							<label class="vca-sp-label">${__('Sales Person')}</label>
							<div class="vca-sp-badge" data-slot="sp_badge">
								<span class="text-muted">${__('Pick a user to resolve…')}</span>
							</div>
						</div>
					</div>
					<div class="vca-picker-hint text-muted small">
						${__('Sales Person is resolved from the Vansale Configuration row that owns this user.')}
					</div>
				</div>

				<div class="vca-stats">
					<div class="vca-stat"><span class="vca-stat-label">${__('On roster')}</span><span class="vca-stat-val" data-slot="stat-roster">0</span></div>
					<div class="vca-stat"><span class="vca-stat-label">${__('In pool')}</span><span class="vca-stat-val" data-slot="stat-pool">0</span></div>
					<div class="vca-stat"><span class="vca-stat-label">${__('Pending changes')}</span><span class="vca-stat-val vca-stat-pending" data-slot="stat-pending">0</span></div>
					<div class="vca-stats-spacer"></div>
					<button class="btn btn-default btn-sm" data-action="reset" disabled>${__('Reset')}</button>
					<button class="btn btn-primary btn-sm" data-action="submit" disabled>${__('Submit Changes')}</button>
				</div>

				<div class="vca-split">
					<!-- LEFT: day-wise roster -->
					<section class="vca-col vca-col-roster">
						<header class="vca-col-head">
							<h4>${__('Driver Roster · by Day')}</h4>
							<span class="vca-col-sub text-muted small">${__('Customers on this driver, grouped by visit day')}</span>
						</header>
						<div class="vca-roster-body" data-slot="roster"></div>
					</section>

					<!-- RIGHT: candidate pool -->
					<section class="vca-col vca-col-pool">
						<header class="vca-col-head">
							<h4>${__('Available Customers')}</h4>
							<div class="vca-pool-controls">
								<label class="vca-toggle" title="${__('Include customers already assigned to another sales person')}">
									<input type="checkbox" data-action="toggle-assigned" />
									<span>${__('Show assigned')}</span>
								</label>
								<div class="input-group input-group-sm vca-search-wrap">
									<input type="search" class="form-control" data-action="search-pool" placeholder="${__('Filter customers…')}" />
								</div>
							</div>
						</header>
						<div class="vca-pool-body" data-slot="pool"></div>
					</section>
				</div>
			</div>
		`);

		this.inject_styles();
	}

	inject_styles() {
		if (document.getElementById('vca-styles')) return;
		const css = `
			.vca-root { padding: 12px 0 40px; display: flex; flex-direction: column; gap: 14px; }
			.vca-picker-card { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: var(--border-radius-md); padding: 16px; }
			.vca-picker-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: end; }
			.vca-picker-hint { margin-top: 10px; }
			.vca-sp-display { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
			.vca-sp-label { font-size: var(--text-sm); color: var(--text-color); margin: 0; font-weight: 500; }
			.vca-sp-badge { padding: 6px 12px; background: var(--bg-light-gray); border: 1px solid var(--border-color); border-radius: var(--border-radius-sm); min-height: 32px; display: flex; align-items: center; font-weight: 500; }
			.vca-sp-badge.resolved { background: var(--blue-50, #eef5ff); border-color: var(--blue-200, #b3d4ff); color: var(--blue-700, #1e5ec8); }

			.vca-stats { display: flex; align-items: center; gap: 16px; padding: 10px 16px; background: var(--card-bg); border: 1px solid var(--border-color); border-radius: var(--border-radius-md); }
			.vca-stat { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; min-width: 80px; }
			.vca-stat-label { font-size: var(--text-xs); color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; font-weight: 600; }
			.vca-stat-val { font-size: var(--text-lg); font-weight: 600; font-variant-numeric: tabular-nums; }
			.vca-stat-pending[data-dirty="1"] { color: var(--orange-500, #f39c12); }
			.vca-stats-spacer { flex: 1; }

			.vca-split { display: grid; grid-template-columns: 1.15fr 1fr; gap: 14px; align-items: stretch; }
			.vca-col { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: var(--border-radius-md); display: flex; flex-direction: column; min-height: 320px; max-height: calc(100vh - 240px); }
			.vca-col-head { padding: 12px 16px; border-bottom: 1px solid var(--border-color); display: flex; align-items: center; justify-content: space-between; gap: 10px; }
			.vca-col-head h4 { margin: 0; font-size: var(--text-md); }
			.vca-col-sub { margin-left: 10px; }
			.vca-search-wrap { width: 220px; }
			.vca-pool-controls { display: flex; align-items: center; gap: 12px; }
			.vca-toggle { display: inline-flex; align-items: center; gap: 6px; margin: 0; font-size: var(--text-sm); color: var(--text-muted); cursor: pointer; }
			.vca-toggle input { margin: 0; }
			.vca-assigned-chip { display: inline-block; font-size: var(--text-xs); color: #8a5a00; background: #fff3cd; border: 1px solid #f1d78c; padding: 1px 8px; border-radius: 10px; margin-top: 2px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
			.vca-btn-move { width: 100%; background: #f0ad4e; color: white; border-color: #eea236; }
			.vca-btn-move:hover { background: #ec971f; border-color: #d58512; color: white; }

			/* LEFT — Roster table */
			.vca-roster-body { flex: 1 1 auto; min-height: 0; overflow-y: auto; }
			.vca-roster-body .vca-table { width: 100%; table-layout: fixed; }
			.vca-roster-body .vca-table th:nth-child(1), .vca-roster-body .vca-table td:nth-child(1) { width: auto; }
			.vca-roster-body .vca-table th:nth-child(2), .vca-roster-body .vca-table td:nth-child(2) { width: 120px; }
			.vca-roster-body .vca-table th:nth-child(3), .vca-roster-body .vca-table td:nth-child(3) { width: 120px; }
			.vca-roster-body .vca-table th:nth-child(4), .vca-roster-body .vca-table td:nth-child(4) { width: 40px; }
			.vca-day-row td { padding: 6px 12px !important; background: var(--bg-light-gray); font-weight: 600; font-size: var(--text-sm); border-top: 1px solid var(--border-color); }
			.vca-day-row.every td { background: #fff6d8; }
			.vca-day-row .vca-day-name { display: inline-block; }
			.vca-day-row .vca-day-count { float: right; font-weight: 500; font-size: var(--text-xs); color: var(--text-muted); background: var(--card-bg); padding: 1px 8px; border-radius: 10px; border: 1px solid var(--border-color); }
			.vca-cust-row.dirty td { background: #fff8ea; }
			.vca-cust-row.removed td { background: #fbeaea; opacity: 0.7; }
			.vca-cust-row td { vertical-align: middle; }
			.vca-row-name { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block; }
			.vca-row-id { font-size: var(--text-xs); color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block; }
			.vca-row-phone { color: var(--text-muted); font-variant-numeric: tabular-nums; font-size: var(--text-sm); }
			.vca-day-select { width: 100%; padding: 3px 6px; font-size: var(--text-sm); }
			.vca-btn-remove { background: transparent; border: none; color: var(--red-500, #e74c3c); cursor: pointer; padding: 4px 6px; border-radius: var(--border-radius-sm); font-size: 14px; }
			.vca-btn-remove:hover { background: #fbe6e6; }
			.vca-day-empty td { color: var(--text-muted); font-size: var(--text-xs); padding: 8px 12px; text-align: center; font-style: italic; }

			/* RIGHT — Pool list as table */
			.vca-pool-body { flex: 1 1 auto; min-height: 0; overflow-y: auto; }
			.vca-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
			.vca-table thead th { position: sticky; top: 0; z-index: 2; background: var(--bg-light-gray); text-align: left; font-weight: 600; color: var(--text-muted); padding: 8px 12px; border-bottom: 1px solid var(--border-color); text-transform: uppercase; letter-spacing: 0.04em; font-size: var(--text-xs); }
			.vca-table tbody tr { border-bottom: 1px solid var(--border-color); }
			.vca-table tbody tr:hover { background: var(--bg-light-gray); }
			.vca-table td { padding: 6px 12px; vertical-align: middle; }
			.vca-pool-name { font-weight: 500; }
			.vca-pool-id { font-size: var(--text-xs); color: var(--text-muted); }
			.vca-pool-phone { color: var(--text-muted); font-variant-numeric: tabular-nums; width: 130px; }
			.vca-pool-add { width: 110px; }
			.vca-btn-add { width: 100%; }
			.vca-empty { color: var(--text-muted); padding: 24px 12px; font-size: var(--text-sm); text-align: center; }

			@media (max-width: 1100px) {
				.vca-roster-body .vca-table th:nth-child(2), .vca-roster-body .vca-table td:nth-child(2) { width: 100px; }
				.vca-roster-body .vca-table th:nth-child(3), .vca-roster-body .vca-table td:nth-child(3) { width: 100px; }
			}
			@media (max-width: 860px) {
				.vca-picker-row, .vca-split { grid-template-columns: 1fr; }
			}
		`;
		$('<style>', { id: 'vca-styles' }).text(css).appendTo(document.head);
	}

	bind_controls() {
		this.user_field = frappe.ui.form.make_control({
			parent: this.$wrap.find('[data-field="user"]').get(0),
			df: {
				fieldtype: 'Link',
				fieldname: 'user',
				label: __('User (Driver)'),
				options: 'User',
				// Restrict picker to Users that appear in Vansale
				// Configuration — admins shouldn't see the 3000+ User
				// roster of the site, just the van drivers.
				get_query: () => ({ query: 'vansale.api.route.van_user_query' }),
				change: () => this.on_user_change(),
			},
			render_input: true,
		});

		this.$wrap.on('click', '[data-action="submit"]', () => this.do_submit());
		this.$wrap.on('click', '[data-action="reset"]', () => this.do_reset());
		this.$wrap.on('click', '[data-action="add"]', (e) => this.do_add($(e.currentTarget).data('customer')));
		this.$wrap.on('click', '[data-action="reassign"]', (e) => this.do_reassign($(e.currentTarget).data('customer')));
		this.$wrap.on('click', '[data-action="remove"]', (e) => this.do_remove($(e.currentTarget).data('customer')));
		this.$wrap.on('change', '[data-action="day-change"]', (e) => this.on_day_change(e));
		this.$wrap.on('input', '[data-action="search-pool"]', (e) => {
			this.pool_filter = e.target.value.toLowerCase();
			this.render_pool();
		});
		this.$wrap.on('change', '[data-action="toggle-assigned"]', (e) => {
			this.include_assigned = e.target.checked ? 1 : 0;
			if (this.sales_person) this.load_data();
		});
	}

	// ────── Data loading ──────

	on_user_change() {
		const u = this.user_field.get_value();
		this.user = u || null;
		const $badge = this.$wrap.find('[data-slot="sp_badge"]');
		if (!u) {
			this.sales_person = null;
			this.roster = [];
			this.pool = [];
			$badge.removeClass('resolved').html(`<span class="text-muted">${__('Pick a user to resolve…')}</span>`);
			this.render_all();
			return;
		}
		$badge.removeClass('resolved').html(`<span class="text-muted">${__('Resolving…')}</span>`);
		frappe.call({
			method: 'vansale.api.route.resolve_user_sales_person',
			args: { user: u },
		}).then((r) => {
			const sp = r && r.message && r.message.sales_person;
			if (sp) {
				this.sales_person = sp;
				$badge.addClass('resolved').html(`<strong>${frappe.utils.escape_html(sp)}</strong>`);
				this.load_data();
			} else {
				this.sales_person = null;
				this.roster = [];
				this.pool = [];
				$badge.removeClass('resolved').html(`<span class="text-danger">${__('No Vansale Configuration mapping for this user')}</span>`);
				this.render_all();
			}
		}, (err) => {
			console.error('[vca] resolve failed:', err);
			$badge.removeClass('resolved').html(
				`<span class="text-danger">${__('Resolve failed — check server log')}</span>`
			);
		});
	}

	load_data() {
		// Parallel: assigned roster + pool (scoped server-side by
		// include_assigned flag).
		const assigned_p = frappe.call({
			method: 'vansale.api.route.list_assigned_customers',
			args: { sales_person: this.sales_person },
		});
		const pool_p = frappe.call({
			method: 'vansale.api.route.list_available_customers',
			args: {
				sales_person: this.sales_person,
				include_assigned: this.include_assigned || 0,
			},
		});
		Promise.all([assigned_p, pool_p]).then(([ar, pr]) => {
			const assigned_rows = (ar && ar.message) || [];
			const pool_rows = (pr && pr.message) || [];
			const assigned_set = new Set(assigned_rows.map((r) => r.customer));
			this.roster = assigned_rows.map((c) => {
				const day = this.csv_to_day(c.visit_days);
				return {
					customer: c.customer,
					customer_name: c.customer_name,
					mobile_no: c.mobile_no,
					day,
					_origDay: day,
					_origAssigned: true,
					_removed: false,
				};
			});
			// Drop rows that are already on this driver's roster — they
			// either came in via include_assigned (same sales_person in
			// group_concat) or via the default view (same sales_person
			// only).
			this.pool = pool_rows
				.filter((c) => !assigned_set.has(c.customer))
				.map((c) => {
					// assigned_to from backend = comma list of sales_persons.
					// Strip THIS sales_person so the chip only shows other
					// drivers' names.
					const others = (c.assigned_to || '')
						.split(',')
						.map((s) => s.trim())
						.filter((s) => s && s !== this.sales_person);
					return {
						customer: c.customer,
						customer_name: c.customer_name || c.customer,
						mobile_no: c.mobile_no,
						assigned_to: others.join(', '),
					};
				});
			this.render_all();
		}, (err) => {
			console.error('[vca] load_data failed:', err);
			frappe.show_alert({ message: __('Failed to load roster — check console'), indicator: 'red' });
		});
	}

	do_reassign(customer) {
		const c = this.pool.find((x) => x.customer === customer);
		if (!c) return;
		const from = c.assigned_to || __('another driver');
		frappe.confirm(
			__('Move {0} from {1} to {2}?', [
				frappe.utils.escape_html(c.customer_name || c.customer),
				frappe.utils.escape_html(from),
				frappe.utils.escape_html(this.sales_person),
			]),
			() => {
				frappe.dom.freeze(__('Reassigning…'));
				frappe.call({
					method: 'vansale.api.route.reassign_customer_sales_person',
					args: { customer, sales_person: this.sales_person },
				}).then(() => {
					frappe.show_alert({ message: __('Customer reassigned'), indicator: 'green' });
					this.load_data();
				}, (err) => {
					console.error('[vca] reassign failed:', err);
					frappe.show_alert({ message: __('Reassign failed'), indicator: 'red' });
				}).finally(() => frappe.dom.unfreeze());
			}
		);
	}

	// ────── Helpers ──────

	// Collapse the CSV into a single bucket key. If CSV is blank, bucket
	// is "every" (visited every day). If CSV has exactly one day, bucket
	// is that day. If multiple, pick the first listed code and warn the
	// admin via data-multi attr so they know the other days exist.
	csv_to_day(csv) {
		if (!csv) return 'every';
		const parts = csv.split(',').map((s) => s.trim().toLowerCase()).filter((s) => DAY_CODES.includes(s));
		if (!parts.length) return 'every';
		return parts[0];
	}

	day_to_csv(day) {
		return day === 'every' ? '' : day;
	}

	dirty_count() {
		let n = 0;
		this.roster.forEach((r) => {
			if (r._removed) n++;
			else if (!r._origAssigned) n++;
			else if (r.day !== r._origDay) n++;
		});
		return n;
	}

	// ────── Actions ──────

	do_add(customer) {
		const idx = this.pool.findIndex((c) => c.customer === customer);
		if (idx === -1) return;
		const c = this.pool[idx];
		this.pool.splice(idx, 1);
		this.roster.push({
			customer: c.customer,
			customer_name: c.customer_name,
			mobile_no: c.mobile_no,
			day: 'every',
			_origDay: null,
			_origAssigned: false,
			_removed: false,
		});
		this.render_all();
	}

	do_remove(customer) {
		const idx = this.roster.findIndex((r) => r.customer === customer);
		if (idx === -1) return;
		const r = this.roster[idx];
		if (!r._origAssigned) {
			// Never persisted; just drop + put back in pool.
			this.roster.splice(idx, 1);
			this.pool.push({
				customer: r.customer,
				customer_name: r.customer_name,
				mobile_no: r.mobile_no,
			});
			this.pool.sort((a, b) => (a.customer_name || a.customer).localeCompare(b.customer_name || b.customer));
		} else {
			// Was assigned on the server — flag for removal on submit.
			r._removed = !r._removed;
		}
		this.render_all();
	}

	on_day_change(e) {
		const customer = $(e.currentTarget).data('customer');
		const day = e.currentTarget.value;
		const row = this.roster.find((r) => r.customer === customer);
		if (!row) return;
		row.day = day;
		this.render_all();
	}

	do_reset() {
		if (!this.sales_person) return;
		frappe.confirm(__('Discard pending changes and reload from server?'), () => {
			this.load_data();
		});
	}

	do_submit() {
		if (!this.sales_person) return;
		const to_unassign = this.roster.filter((r) => r._origAssigned && r._removed).map((r) => r.customer);
		const to_assign = this.roster.filter((r) => !r._origAssigned && !r._removed).map((r) => r.customer);
		// days changes: for every remaining (non-removed) row whose day CSV differs from _origDay csv.
		const day_changes = new Map(); // day_csv → [customers]
		this.roster.forEach((r) => {
			if (r._removed) return;
			const orig_csv = r._origDay == null ? null : this.day_to_csv(r._origDay);
			const new_csv = this.day_to_csv(r.day);
			const is_new = !r._origAssigned;
			if (is_new || orig_csv !== new_csv) {
				const arr = day_changes.get(new_csv) || [];
				arr.push(r.customer);
				day_changes.set(new_csv, arr);
			}
		});
		if (!to_unassign.length && !to_assign.length && day_changes.size === 0) {
			frappe.show_alert({ message: __('Nothing to submit'), indicator: 'blue' });
			return;
		}

		const steps = [];
		if (to_assign.length) {
			steps.push(() => frappe.call({
				method: 'vansale.api.route.bulk_assign_sales_person',
				args: { sales_person: this.sales_person, customers: to_assign },
			}));
		}
		if (to_unassign.length) {
			steps.push(() => frappe.call({
				method: 'vansale.api.route.bulk_unassign_sales_person',
				args: { sales_person: this.sales_person, customers: to_unassign },
			}));
		}
		// bulk_set_visit_days writes the same day csv for a batch of customers
		day_changes.forEach((customers, day_csv) => {
			const days_payload = day_csv ? [day_csv] : [];
			steps.push(() => frappe.call({
				method: 'vansale.api.route.bulk_set_visit_days',
				args: { customers, days: days_payload },
			}));
		});

		const run = (i) => {
			if (i >= steps.length) {
				frappe.show_alert({
					message: __('Roster saved — {0} added, {1} removed, {2} day edits', [
						to_assign.length, to_unassign.length, Array.from(day_changes.values()).reduce((a, b) => a + b.length, 0),
					]),
					indicator: 'green',
				});
				this.load_data();
				return;
			}
			steps[i]().then(() => run(i + 1), (err) => {
				console.error('[vca] submit step failed:', err);
				frappe.show_alert({ message: __('Submit failed at step {0}', [i + 1]), indicator: 'red' });
			});
		};
		frappe.dom.freeze(__('Saving roster…'));
		Promise.resolve().then(() => run(0)).finally(() => frappe.dom.unfreeze());
	}

	// ────── Rendering ──────

	render_all() {
		this.render_roster();
		this.render_pool();
		this.render_stats();
	}

	render_stats() {
		this.$wrap.find('[data-slot="stat-roster"]').text(this.roster.filter((r) => !r._removed).length);
		this.$wrap.find('[data-slot="stat-pool"]').text(this.pool.length);
		const dirty = this.dirty_count();
		const $pending = this.$wrap.find('[data-slot="stat-pending"]');
		$pending.text(dirty).attr('data-dirty', dirty > 0 ? '1' : '0');
		this.$wrap.find('[data-action="submit"]').prop('disabled', !this.sales_person || dirty === 0);
		this.$wrap.find('[data-action="reset"]').prop('disabled', !this.sales_person || dirty === 0);
	}

	render_roster() {
		const $root = this.$wrap.find('[data-slot="roster"]');
		if (!this.sales_person) {
			$root.html(`<div class="vca-empty">${__('Pick a user to begin.')}</div>`);
			return;
		}
		if (!this.roster.length) {
			$root.html(`<div class="vca-empty">${__('No customers assigned yet. Add from the right panel.')}</div>`);
			return;
		}
		const buckets = { every: [] };
		DAY_CODES.forEach((d) => (buckets[d] = []));
		this.roster.forEach((r) => {
			buckets[r.day || 'every'].push(r);
		});
		const order = ['every', ...DAY_CODES];
		const body = order.map((key) => {
			const rows = buckets[key];
			const title = key === 'every' ? __('Every day') : DAY_SHORT[key];
			const head = `
				<tr class="vca-day-row${key === 'every' ? ' every' : ''}">
					<td colspan="4">
						<span class="vca-day-name">${title}</span>
						<span class="vca-day-count">${rows.length}</span>
					</td>
				</tr>
			`;
			const body_rows = rows.length
				? rows.map((r) => this.roster_row_html(r)).join('')
				: `<tr class="vca-day-empty"><td colspan="4">${__('No customers')}</td></tr>`;
			return head + body_rows;
		}).join('');
		$root.html(`
			<table class="vca-table">
				<thead><tr>
					<th>${__('Customer')}</th>
					<th>${__('Phone')}</th>
					<th>${__('Day')}</th>
					<th></th>
				</tr></thead>
				<tbody>${body}</tbody>
			</table>
		`);
	}

	roster_row_html(r) {
		const dirty_class = r._removed
			? ' removed'
			: (!r._origAssigned || (r.day !== r._origDay) ? ' dirty' : '');
		const day_options = [
			{ v: 'every', l: __('Every day') },
			...DAY_CODES.map((d) => ({ v: d, l: DAY_SHORT[d] })),
		].map((o) => `<option value="${o.v}"${r.day === o.v ? ' selected' : ''}>${o.l}</option>`).join('');
		const phone = r.mobile_no ? frappe.utils.escape_html(r.mobile_no) : '—';
		const remove_title = r._removed ? __('Undo remove') : __('Remove from roster');
		const remove_icon = r._removed ? '↺' : '✕';
		const cust = frappe.utils.escape_html(r.customer);
		return `
			<tr class="vca-cust-row${dirty_class}" data-customer="${cust}">
				<td>
					<span class="vca-row-name">${frappe.utils.escape_html(r.customer_name || r.customer)}</span>
					<span class="vca-row-id">${cust}</span>
				</td>
				<td class="vca-row-phone">${phone}</td>
				<td>
					<select class="form-control vca-day-select" data-action="day-change" data-customer="${cust}" ${r._removed ? 'disabled' : ''}>
						${day_options}
					</select>
				</td>
				<td>
					<button class="vca-btn-remove" data-action="remove" data-customer="${cust}" title="${remove_title}">${remove_icon}</button>
				</td>
			</tr>
		`;
	}

	render_pool() {
		const $root = this.$wrap.find('[data-slot="pool"]');
		if (!this.sales_person) {
			$root.html(`<div class="vca-empty">${__('Pick a user to begin.')}</div>`);
			return;
		}
		const q = this.pool_filter;
		const rows = q
			? this.pool.filter((c) => {
				const hay = `${c.customer_name || ''} ${c.customer || ''} ${c.mobile_no || ''}`.toLowerCase();
				return hay.indexOf(q) !== -1;
			})
			: this.pool;
		if (!rows.length) {
			$root.html(`<div class="vca-empty">${this.pool.length ? __('No customers match the filter.') : __('Every customer is already on the roster.')}</div>`);
			return;
		}
		const body = rows.map((c) => {
			const cust = frappe.utils.escape_html(c.customer);
			const is_assigned = !!c.assigned_to;
			const chip = is_assigned
				? `<span class="vca-assigned-chip" title="${__('Already assigned to {0}', [frappe.utils.escape_html(c.assigned_to)])}">↔ ${frappe.utils.escape_html(c.assigned_to)}</span>`
				: '';
			const btn = is_assigned
				? `<button class="btn btn-xs vca-btn-move" data-action="reassign" data-customer="${cust}" title="${__('Unassign from other driver and assign to this one')}">${__('Move')}</button>`
				: `<button class="btn btn-primary btn-xs vca-btn-add" data-action="add" data-customer="${cust}">${__('Add')}</button>`;
			return `
				<tr data-customer="${cust}">
					<td>
						<span class="vca-pool-name">${frappe.utils.escape_html(c.customer_name || c.customer)}</span>
						<span class="vca-pool-id d-block">${cust}</span>
						${chip}
					</td>
					<td class="vca-pool-phone">${c.mobile_no ? frappe.utils.escape_html(c.mobile_no) : '—'}</td>
					<td class="vca-pool-add">${btn}</td>
				</tr>
			`;
		}).join('');
		$root.html(`
			<table class="vca-table">
				<thead><tr>
					<th>${__('Customer')}</th>
					<th class="vca-pool-phone">${__('Phone')}</th>
					<th class="vca-pool-add"></th>
				</tr></thead>
				<tbody>${body}</tbody>
			</table>
		`);
	}
}
