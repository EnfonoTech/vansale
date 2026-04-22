// Van Driver Roster — read-only viewer.
//
// Driver dropdown selector + day-wise grouped customer view.
// Day buckets mirror the Van Customer Assignment roster (Sat → Fri, Every day).
// No mutations here — use Van Customer Assignment for changes.

frappe.pages['van-driver-roster'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Van Driver Roster'),
		single_column: true,
	});
	new VanDriverRoster(page);
};

const VDR_DAY_ORDER = ['sat', 'sun', 'mon', 'tue', 'wed', 'thu', 'fri'];
const VDR_DAY_LABEL = {
	sat: __('Saturday'),
	sun: __('Sunday'),
	mon: __('Monday'),
	tue: __('Tuesday'),
	wed: __('Wednesday'),
	thu: __('Thursday'),
	fri: __('Friday'),
};

class VanDriverRoster {
	constructor(page) {
		this.page = page;
		this.$wrap = $(page.body);
		this.rows = [];
		this.selected_user = ''; // empty = all drivers
		this.inject_styles();
		this.render_scaffold();
		this.bind();
		this.page.set_primary_action(__('Reload'), () => this.load());
		this.page.set_secondary_action(__('Open Assignment Page'), () => {
			frappe.set_route('van-customer-assignment');
		});
		this.load();
	}

	inject_styles() {
		if (document.getElementById('vdr-styles')) return;
		const css = `
			.vdr-root { padding: 12px 0 40px; display: flex; flex-direction: column; gap: 14px; }
			.vdr-toolbar { display: flex; align-items: center; gap: 12px; background: var(--card-bg); border: 1px solid var(--border-color); border-radius: var(--border-radius-md); padding: 10px 16px; flex-wrap: wrap; }
			.vdr-toolbar label { font-size: var(--text-xs); color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; font-weight: 600; margin: 0; }
			.vdr-driver-select { min-width: 320px; }
			.vdr-stats { display: flex; gap: 16px; margin-left: auto; font-size: var(--text-sm); color: var(--text-muted); }
			.vdr-stats strong { color: var(--text-color); font-variant-numeric: tabular-nums; }
			.vdr-driver-card { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: var(--border-radius-md); overflow: hidden; }
			.vdr-driver-head { padding: 12px 16px; border-bottom: 1px solid var(--border-color); display: flex; align-items: center; gap: 12px; }
			.vdr-driver-name { font-weight: 600; font-size: var(--text-md); }
			.vdr-driver-sp { color: var(--text-muted); font-size: var(--text-sm); }
			.vdr-driver-count { margin-left: auto; font-size: var(--text-xs); color: var(--text-muted); background: var(--bg-light-gray); padding: 2px 10px; border-radius: 12px; border: 1px solid var(--border-color); font-variant-numeric: tabular-nums; }
			.vdr-driver-card.empty .vdr-driver-count { background: #fbeaea; color: #b14040; border-color: #e9b3b3; }
			.vdr-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
			.vdr-table thead th { background: var(--bg-light-gray); text-align: left; font-weight: 600; color: var(--text-muted); padding: 8px 12px; border-bottom: 1px solid var(--border-color); text-transform: uppercase; letter-spacing: 0.04em; font-size: var(--text-xs); }
			.vdr-table tbody tr { border-bottom: 1px solid var(--border-color); }
			.vdr-table tbody tr:last-child { border-bottom: none; }
			.vdr-table tbody tr:hover { background: var(--bg-light-gray); }
			.vdr-table td { padding: 6px 12px; }
			.vdr-cust-name { font-weight: 500; }
			.vdr-cust-id { font-size: var(--text-xs); color: var(--text-muted); display: block; }
			.vdr-phone { color: var(--text-muted); font-variant-numeric: tabular-nums; width: 160px; }
			.vdr-day-divider td { background: #f4f8ff; color: #1e5ec8; font-weight: 600; padding: 8px 12px; text-transform: uppercase; letter-spacing: 0.04em; font-size: var(--text-xs); border-top: 1px solid #d6e4ff; border-bottom: 1px solid #d6e4ff; }
			.vdr-day-divider.every td { background: #fff6d8; color: #8a5a00; border-color: #f1d78c; }
			.vdr-day-divider .vdr-day-count { float: right; background: rgba(255,255,255,0.6); padding: 1px 8px; border-radius: 10px; font-size: 10px; }
			.vdr-day-empty td { padding: 10px 14px; color: var(--text-muted); font-style: italic; font-size: var(--text-xs); }
			.vdr-other-days { font-size: 10px; color: var(--text-muted); }
			.vdr-empty-body { padding: 20px 16px; text-align: center; color: var(--text-muted); font-size: var(--text-sm); font-style: italic; }
			.vdr-empty-root { padding: 40px 16px; text-align: center; color: var(--text-muted); }
		`;
		$('<style>', { id: 'vdr-styles' }).text(css).appendTo(document.head);
	}

	render_scaffold() {
		this.$wrap.html(`
			<div class="vdr-root">
				<div class="vdr-toolbar">
					<label for="vdr-driver-select">${__('Driver')}</label>
					<select id="vdr-driver-select" class="form-control input-sm vdr-driver-select" data-action="pick"></select>
					<div class="vdr-stats">
						<span>${__('Drivers')}: <strong data-slot="stat-drivers">0</strong></span>
						<span>${__('Customers')}: <strong data-slot="stat-customers">0</strong></span>
					</div>
				</div>
				<div data-slot="drivers"></div>
			</div>
		`);
	}

	bind() {
		this.$wrap.on('change', '[data-action="pick"]', (e) => {
			this.selected_user = e.target.value || '';
			this.render();
		});
	}

	load() {
		frappe.dom.freeze(__('Loading roster…'));
		const done = () => { try { frappe.dom.unfreeze(); } catch (e) { /* noop */ } };
		frappe.call({
			method: 'vansale.api.route.driver_roster_overview',
			callback: (r) => {
				try {
					this.rows = (r && r.message) || [];
					this.render_dropdown();
					this.render();
				} catch (e) {
					console.error('[vdr] render failed', e);
					frappe.show_alert({ message: __('Render failed: ') + (e.message || e), indicator: 'red' });
				} finally {
					done();
				}
			},
			error: (err) => {
				console.error('[vdr] load failed', err);
				frappe.show_alert({ message: __('Failed to load roster'), indicator: 'red' });
				done();
			},
		});
	}

	grouped() {
		// Collapse (user, customer) rows into one entry per driver.
		const map = new Map();
		this.rows.forEach((r) => {
			if (!map.has(r.user)) {
				map.set(r.user, {
					user: r.user,
					full_name: r.full_name || r.user,
					sales_person: r.sales_person,
					customers: [],
				});
			}
			if (r.customer) {
				map.get(r.user).customers.push({
					customer: r.customer,
					customer_name: r.customer_name,
					mobile_no: r.mobile_no,
					visit_days: r.visit_days || '',
				});
			}
		});
		return Array.from(map.values()).sort((a, b) => (a.full_name || '').localeCompare(b.full_name || ''));
	}

	render_dropdown() {
		const $sel = this.$wrap.find('[data-action="pick"]');
		const groups = this.grouped();
		const opts = [`<option value="">${__('— All drivers —')}</option>`]
			.concat(groups.map((g) => {
				const count = g.customers.length;
				const label = `${frappe.utils.escape_html(g.full_name || g.user)} · SP: ${frappe.utils.escape_html(g.sales_person || '—')} (${count})`;
				return `<option value="${frappe.utils.escape_html(g.user)}">${label}</option>`;
			}));
		$sel.html(opts.join(''));
		if (this.selected_user) $sel.val(this.selected_user);
	}

	render() {
		const all_groups = this.grouped();
		const groups = this.selected_user
			? all_groups.filter((g) => g.user === this.selected_user)
			: all_groups;
		const $root = this.$wrap.find('[data-slot="drivers"]');
		const total_cust = groups.reduce((acc, g) => acc + g.customers.length, 0);
		this.$wrap.find('[data-slot="stat-drivers"]').text(groups.length);
		this.$wrap.find('[data-slot="stat-customers"]').text(total_cust);

		if (!groups.length) {
			$root.html(`<div class="vdr-empty-root">${__('No drivers to show.')}</div>`);
			return;
		}
		const html = groups.map((g) => this.render_driver(g)).join('');
		$root.html(html);
	}

	render_driver(g) {
		const empty_cls = g.customers.length ? '' : ' empty';
		const body = g.customers.length
			? this.render_day_buckets(g.customers)
			: `<div class="vdr-empty-body">${__('No customers assigned to this driver yet.')}</div>`;
		return `
			<div class="vdr-driver-card${empty_cls}">
				<div class="vdr-driver-head">
					<span class="vdr-driver-name">${frappe.utils.escape_html(g.full_name || g.user)}</span>
					<span class="vdr-driver-sp">· ${frappe.utils.escape_html(g.user)} · SP: ${frappe.utils.escape_html(g.sales_person || '—')}</span>
					<span class="vdr-driver-count">${g.customers.length} ${__('customers')}</span>
				</div>
				${body}
			</div>
		`;
	}

	render_day_buckets(customers) {
		// Build buckets: one per day (sat..fri) + 'every' for customers with no visit_days.
		// A customer can appear in multiple day buckets (one row per day).
		const buckets = {};
		VDR_DAY_ORDER.forEach((d) => (buckets[d] = []));
		buckets.every = [];

		customers.forEach((c) => {
			const set = new Set(
				(c.visit_days || '')
					.split(',')
					.map((s) => s.trim().toLowerCase())
					.filter(Boolean)
			);
			if (!set.size) {
				buckets.every.push({ ...c, day: null, days_set: set });
				return;
			}
			VDR_DAY_ORDER.forEach((d) => {
				if (set.has(d)) buckets[d].push({ ...c, day: d, days_set: set });
			});
		});

		const order = VDR_DAY_ORDER.concat(['every']);
		const rows_html = order
			.map((key) => {
				const rows = buckets[key];
				if (!rows.length) return ''; // skip empty days
				const title = key === 'every' ? __('Every day') : VDR_DAY_LABEL[key];
				const divider_cls = key === 'every' ? 'vdr-day-divider every' : 'vdr-day-divider';
				const head = `<tr class="${divider_cls}"><td colspan="3">${title}<span class="vdr-day-count">${rows.length}</span></td></tr>`;
				const body = rows.map((c) => this.cust_row_html(c)).join('');
				return head + body;
			})
			.join('');

		return `
			<table class="vdr-table">
				<thead><tr>
					<th>${__('Customer')}</th>
					<th>${__('Phone')}</th>
					<th>${__('Other days')}</th>
				</tr></thead>
				<tbody>${rows_html}</tbody>
			</table>
		`;
	}

	cust_row_html(c) {
		const other = Array.from(c.days_set || [])
			.filter((d) => d !== c.day)
			.map((d) => VDR_DAY_LABEL[d] || d);
		const other_html = other.length
			? `<span class="vdr-other-days">${other.join(', ')}</span>`
			: '<span class="vdr-other-days">—</span>';
		return `
			<tr>
				<td>
					<span class="vdr-cust-name">${frappe.utils.escape_html(c.customer_name || c.customer)}</span>
					<span class="vdr-cust-id">${frappe.utils.escape_html(c.customer)}</span>
				</td>
				<td class="vdr-phone">${c.mobile_no ? frappe.utils.escape_html(c.mobile_no) : '—'}</td>
				<td>${other_html}</td>
			</tr>
		`;
	}
}
