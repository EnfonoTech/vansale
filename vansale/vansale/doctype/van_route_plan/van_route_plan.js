// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Desk-side controller for Van Route Plan. Two jobs:
//   (1) Filter the stops.customer picker to customers assigned to the
//       plan's Sales User via their Sales Person on Sales Team. This is
//       the cure for the 2026-04-22 feedback "only few customers directly
//       added as sales person showing" — the picker was unfiltered, so
//       admins had to scroll the full customer list and pick wrong.
//   (2) Surface a helper message under Days when frequency=Monthly so
//       admins know the CSV format (1,15,28) without opening the docs.
frappe.ui.form.on("Van Route Plan", {
  refresh(frm) {
    // Scoped customer picker on the child table.
    frm.set_query("customer", "stops", () => ({
      query: "vansale.api.route.customer_query",
      filters: { user: frm.doc.user || "" },
    }));
  },

  user(frm) {
    // If the admin changes the salesperson after adding stops, clear
    // the cached picker results so the next click re-queries with the
    // new filter.
    frm.refresh_field("stops");
  },
});
