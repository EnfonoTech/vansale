// Van Customer Assignment — desk-side admin utility.
//
// Replaces the old Van Route Plan customer picker screen. Admin picks a
// driver (or a Sales Person directly), sees every customer already tagged
// to that Sales Person via the Customer's Sales Team child table, and
// can bulk-assign or bulk-unassign customers without opening each
// Customer form. All mutation goes through the vansale.api.route
// endpoints so permission checks and idempotency stay server-side.

frappe.pages['van-customer-assignment'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Van Customer Assignment'),
		single_column: true,
	});
	new VanCustomerAssignment(page);
};

class VanCustomerAssignment {
	constructor(page) {
		this.page = page;
		this.$wrap = $(page.body);
		this.user = null;
		this.sales_person = null;
		this.assigned = [];
		this.to_add = [];
		this.render_scaffold();
		this.bind_controls();
	}

	render_scaffold() {
		this.$wrap.html(`
			<div class="vca-root">
				<div class="vca-picker-card">
					<div class="vca-picker-row">
						<div class="vca-field" data-field="user"></div>
						<div class="vca-field" data-field="sales_person"></div>
					</div>
					<div class="vca-picker-hint text-muted small">
						${__('Pick a user to resolve their Sales Person from Vansale Configuration, or type a Sales Person directly.')}
					</div>
				</div>

				<div class="vca-split">
					<section class="vca-col">
						<header class="vca-col-head">
							<h4>${__('Currently Assigned')}</h4>
							<span class="vca-count badge" data-count="assigned">0</span>
						</header>
						<div class="vca-list" data-list="assigned"></div>
						<div class="vca-col-foot">
							<button class="btn btn-danger btn-sm" data-action="unassign" disabled>
								${__('Remove Selected')}
							</button>
						</div>
					</section>

					<section class="vca-col">
						<header class="vca-col-head">
							<h4>${__('Add Customers')}</h4>
							<span class="vca-count badge badge-info" data-count="to_add">0</span>
						</header>
						<div class="vca-field" data-field="picker"></div>
						<div class="vca-list" data-list="to_add"></div>
						<div class="vca-col-foot">
							<button class="btn btn-primary btn-sm" data-action="assign" disabled>
								${__('Assign Selected')}
							</button>
						</div>
					</section>
				</div>
			</div>
		`);

		this.inject_styles();
	}

	inject_styles() {
		if (document.getElementById('vca-styles')) return;
		const css = `
			.vca-root { padding: 12px 0 40px; display: flex; flex-direction: column; gap: 16px; }
			.vca-picker-card { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: var(--border-radius-md); padding: 16px; }
			.vca-picker-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
			.vca-picker-hint { margin-top: 10px; }
			.vca-split { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
			.vca-col { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: var(--border-radius-md); display: flex; flex-direction: column; min-height: 320px; }
			.vca-col-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid var(--border-color); }
			.vca-col-head h4 { margin: 0; font-size: var(--text-md); }
			.vca-list { flex: 1 1 auto; overflow-y: auto; padding: 4px 8px; max-height: 420px; }
			.vca-col-foot { padding: 10px 16px; border-top: 1px solid var(--border-color); display: flex; justify-content: flex-end; }
			.vca-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: var(--border-radius-sm); cursor: pointer; }
			.vca-row:hover { background: var(--bg-light-gray); }
			.vca-row input[type="checkbox"] { flex-shrink: 0; }
			.vca-row .vca-row-main { display: flex; flex-direction: column; min-width: 0; }
			.vca-row .vca-row-name { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
			.vca-row .vca-row-meta { color: var(--text-muted); font-size: var(--text-sm); }
			.vca-empty { color: var(--text-muted); padding: 18px 12px; font-size: var(--text-sm); text-align: center; }
			.vca-count { font-variant-numeric: tabular-nums; }
			.vca-field { min-width: 0; }
			@media (max-width: 860px) {
				.vca-picker-row, .vca-split { grid-template-columns: 1fr; }
			}
		`;
		$('<style>', { id: 'vca-styles' }).text(css).appendTo(document.head);
	}

	bind_controls() {
		// User link — resolves to Sales Person via Vansale Configuration.
		this.user_field = frappe.ui.form.make_control({
			parent: this.$wrap.find('[data-field="user"]').get(0),
			df: {
				fieldtype: 'Link',
				fieldname: 'user',
				label: __('User (Driver)'),
				options: 'User',
				change: () => this.on_user_change(),
			},
			render_input: true,
		});

		this.sp_field = frappe.ui.form.make_control({
			parent: this.$wrap.find('[data-field="sales_person"]').get(0),
			df: {
				fieldtype: 'Link',
				fieldname: 'sales_person',
				label: __('Sales Person'),
				options: 'Sales Person',
				change: () => this.on_sp_change(),
			},
			render_input: true,
		});

		// Customer picker for the "add" column. Uses the same
		// unassigned-only query the server exposes for customer_query.
		this.picker_field = frappe.ui.form.make_control({
			parent: this.$wrap.find('[data-field="picker"]').get(0),
			df: {
				fieldtype: 'Link',
				fieldname: 'picker',
				label: __('Find Customer'),
				options: 'Customer',
				get_query: () => {
					if (!this.sales_person) return {};
					return {
						query: 'vansale.api.route.customer_query',
						filters: {
							sales_person: this.sales_person,
							unassigned_only: 1,
						},
					};
				},
				change: () => this.on_pick_customer(),
			},
			render_input: true,
		});

		this.$wrap.on('click', '[data-action="assign"]', () => this.do_assign());
		this.$wrap.on('click', '[data-action="unassign"]', () => this.do_unassign());
		this.$wrap.on('change', '.vca-list input[type="checkbox"]', () => this.refresh_buttons());
	}

	on_user_change() {
		const u = this.user_field.get_value();
		this.user = u || null;
		if (!u) return;
		// sales_person lives on the `Vansale Configuration User` child table,
		// not the parent — hence the direct child-doctype lookup.
		frappe.db.get_value('Vansale Configuration User', { user: u }, 'sales_person')
			.then((r) => {
				const sp = r && r.message && r.message.sales_person;
				if (sp) {
					this.sp_field.set_value(sp);
				} else {
					frappe.show_alert({
						message: __('No Vansale Configuration mapping found for {0}', [u]),
						indicator: 'orange',
					});
					this.sales_person = null;
					this.assigned = [];
					this.render_lists();
				}
			});
	}

	on_sp_change() {
		const sp = this.sp_field.get_value();
		this.sales_person = sp || null;
		this.to_add = [];
		if (!sp) {
			this.assigned = [];
			this.render_lists();
			return;
		}
		this.load_assigned();
	}

	load_assigned() {
		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Customer',
				filters: [['Sales Team', 'sales_person', '=', this.sales_person]],
				fields: ['name', 'customer_name', 'mobile_no'],
				limit_page_length: 0,
				order_by: 'customer_name asc',
			},
		}).then((r) => {
			this.assigned = (r.message || []).map((c) => ({
				customer: c.name,
				customer_name: c.customer_name,
				mobile_no: c.mobile_no,
			}));
			this.render_lists();
		});
	}

	on_pick_customer() {
		const picked = this.picker_field.get_value();
		if (!picked) return;
		if (this.assigned.some((r) => r.customer === picked)) {
			frappe.show_alert({ message: __('Already assigned'), indicator: 'orange' });
			this.picker_field.set_value('');
			return;
		}
		if (this.to_add.some((r) => r.customer === picked)) {
			this.picker_field.set_value('');
			return;
		}
		// Pull the full name for the chip label.
		frappe.db.get_value('Customer', picked, ['customer_name', 'mobile_no']).then((r) => {
			const v = (r && r.message) || {};
			this.to_add.push({
				customer: picked,
				customer_name: v.customer_name || picked,
				mobile_no: v.mobile_no || null,
				_checked: true,
			});
			this.picker_field.set_value('');
			this.render_lists();
		});
	}

	render_lists() {
		const $assigned = this.$wrap.find('[data-list="assigned"]');
		const $to_add = this.$wrap.find('[data-list="to_add"]');

		if (!this.sales_person) {
			$assigned.html(`<div class="vca-empty">${__('Pick a user or Sales Person to begin.')}</div>`);
		} else if (this.assigned.length === 0) {
			$assigned.html(`<div class="vca-empty">${__('No customers assigned yet.')}</div>`);
		} else {
			$assigned.html(this.assigned.map((c) => this.row_html(c, 'assigned')).join(''));
		}

		if (!this.sales_person) {
			$to_add.html(`<div class="vca-empty">${__('Select a Sales Person above.')}</div>`);
		} else if (this.to_add.length === 0) {
			$to_add.html(`<div class="vca-empty">${__('Find customers with the picker above.')}</div>`);
		} else {
			$to_add.html(this.to_add.map((c) => this.row_html(c, 'to_add')).join(''));
		}

		this.$wrap.find('[data-count="assigned"]').text(this.assigned.length);
		this.$wrap.find('[data-count="to_add"]').text(this.to_add.length);
		this.refresh_buttons();
	}

	row_html(c, kind) {
		const checked = c._checked ? 'checked' : '';
		const meta = c.mobile_no ? `<span class="vca-row-meta">${frappe.utils.escape_html(c.mobile_no)}</span>` : '';
		return `
			<label class="vca-row" data-kind="${kind}" data-customer="${frappe.utils.escape_html(c.customer)}">
				<input type="checkbox" ${checked} />
				<div class="vca-row-main">
					<span class="vca-row-name">${frappe.utils.escape_html(c.customer_name || c.customer)}</span>
					${meta}
				</div>
			</label>
		`;
	}

	refresh_buttons() {
		// Sync _checked flags back into state then toggle action buttons.
		this.$wrap.find('.vca-list .vca-row').each((_, el) => {
			const $el = $(el);
			const kind = $el.data('kind');
			const customer = $el.data('customer');
			const checked = $el.find('input[type="checkbox"]').is(':checked');
			const list = kind === 'assigned' ? this.assigned : this.to_add;
			const row = list.find((r) => r.customer === customer);
			if (row) row._checked = checked;
		});
		const any_assigned = this.assigned.some((r) => r._checked);
		const any_to_add = this.to_add.some((r) => r._checked);
		this.$wrap.find('[data-action="unassign"]').prop('disabled', !any_assigned || !this.sales_person);
		this.$wrap.find('[data-action="assign"]').prop('disabled', !any_to_add || !this.sales_person);
	}

	do_assign() {
		const picked = this.to_add.filter((r) => r._checked).map((r) => r.customer);
		if (!picked.length) return;
		frappe.call({
			method: 'vansale.api.route.bulk_assign_sales_person',
			args: {
				sales_person: this.sales_person,
				customers: picked,
			},
			freeze: true,
			freeze_message: __('Assigning…'),
		}).then((r) => {
			const res = r.message || {};
			frappe.show_alert({
				message: __('{0} assigned · {1} already tagged', [res.assigned || 0, res.skipped || 0]),
				indicator: 'green',
			});
			// Move the successfully assigned ones into the assigned column.
			this.to_add = this.to_add.filter((r) => !picked.includes(r.customer));
			this.load_assigned();
		});
	}

	do_unassign() {
		const picked = this.assigned.filter((r) => r._checked).map((r) => r.customer);
		if (!picked.length) return;
		frappe.confirm(
			__('Remove Sales Person {0} from {1} customers?', [this.sales_person, picked.length]),
			() => {
				frappe.call({
					method: 'vansale.api.route.bulk_unassign_sales_person',
					args: {
						sales_person: this.sales_person,
						customers: picked,
					},
					freeze: true,
					freeze_message: __('Removing…'),
				}).then((r) => {
					const res = r.message || {};
					frappe.show_alert({
						message: __('{0} unassigned', [res.unassigned || 0]),
						indicator: 'orange',
					});
					this.load_assigned();
				});
			}
		);
	}
}
