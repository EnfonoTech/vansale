/**
 * sf_trading: Create New Customer dialog.
 * Registered on: Sales Invoice, Sales Order, Quotation, Delivery Note.
 *
 * B2C (Individual) — Name + Mobile required only.
 * B2B (Company)    — Name + Mobile + VAT + CRN (optional) + Address block.
 *
 * Saudi Arabia companies:
 *   - VAT mandatory for B2B, exactly 15 digits, starts and ends with 3.
 *   - Full address (Line 1, Building No, District, City, Postal Code) mandatory for B2B.
 *   - Postal Code exactly 5 digits.
 * Non-Saudi companies:
 *   - VAT, address, postal code shown but not mandatory, no format enforced.
 */

["Sales Invoice", "Sales Order", "Delivery Note"].forEach(function (dt) {
    frappe.ui.form.on(dt, {
        refresh: function (frm) {
            sf_add_create_customer_btn(frm, "customer");
        },
    });
});

frappe.ui.form.on("Quotation", {
    refresh: function (frm) {
        if (frm.doc.quotation_to && frm.doc.quotation_to !== "Customer") return;
        sf_add_create_customer_btn(frm, "party_name");
    },
    quotation_to: function (frm) {
        frm.fields_dict.party_name &&
            frm.fields_dict.party_name.$wrapper
                .parent()
                .find(".sf-create-customer-btn")
                .remove();
        if (frm.doc.quotation_to === "Customer") {
            sf_add_create_customer_btn(frm, "party_name");
        }
    },
});

function sf_add_create_customer_btn(frm, field_name) {
    if (frm.doc.docstatus !== 0) return;
    if (!frm.fields_dict[field_name]) return;

    var $field = frm.fields_dict[field_name].$wrapper;
    if ($field.parent().find(".sf-create-customer-btn").length) return;

    var $btn = $(
        '<button type="button" class="btn btn-sm btn-secondary sf-create-customer-btn"'
        + ' style="margin-bottom:5px;">'
        + '<i class="fa fa-plus"></i> ' + __("Create New Customer")
        + "</button>"
    );
    $btn.on("click", function () {
        if (frm.doctype === "Quotation") {
            frm.set_value("quotation_to", "Customer");
        }
        sf_open_create_customer_dialog(frm, field_name);
    });
    $field.before($btn);
}

function sf_open_create_customer_dialog(frm, field_name) {
    var company = frm.doc.company || frappe.defaults.get_default("company");

    var OVERRIDE_ROLES = ["Sales Manager", "Sales Master Manager", "System Manager"];
    var can_override = (frappe.user_roles || []).some(function (r) {
        return OVERRIDE_ROLES.indexOf(r) !== -1;
    });

    var can_b2b = (frappe.user_roles || []).some(function (r) {
        return ["B2B Creator", "System Manager", "Administrator"].indexOf(r) !== -1;
    });

    frappe.db.get_value("Company", company, ["country", "default_currency"], function (r) {
        var company_country = (r && r.country) || "";
        var default_currency = (r && r.default_currency) || null;
        var is_saudi = company_country === "Saudi Arabia";

        var b2b = "eval:doc.buyer_kind === 'B2B (Company)'";
        var b2b_saudi = is_saudi ? b2b : "";

        var buyer_kind_field = can_b2b
            ? {
                fieldname: "buyer_kind",
                fieldtype: "Select",
                label: __("Customer Kind"),
                options: "B2C (Individual)\nB2B (Company)",
                default: "B2C (Individual)",
                reqd: 1,
                description: __("B2C: Name + Mobile only. B2B: VAT and address details."),
            }
            : {
                fieldname: "buyer_kind",
                fieldtype: "Data",
                label: __("Customer Kind"),
                default: "B2C (Individual)",
                hidden: 1,
                read_only: 1,
            };

        var d = new frappe.ui.Dialog({
            title: __("Create New Customer"),
            size: "large",
            fields: [
                buyer_kind_field,
                { fieldtype: "Section Break" },
                {
                    fieldname: "customer_name",
                    fieldtype: "Data",
                    label: __("Customer Name"),
                    reqd: 1,
                },
                {
                    fieldname: "mobile_no",
                    fieldtype: "Data",
                    label: __("Mobile No"),
                    reqd: 1,
                },
                {
                    fieldname: "email_id",
                    fieldtype: "Data",
                    label: __("Email ID"),
                },
                // ── B2B Details ──────────────────────────────────────────────
                {
                    fieldtype: "Section Break",
                    label: __("B2B Details"),
                    depends_on: b2b,
                },
                {
                    fieldname: "tax_id",
                    fieldtype: "Data",
                    label: __("VAT Registration Number"),
                    depends_on: b2b,
                    mandatory_depends_on: b2b,
                    description: is_saudi
                        ? __("Exactly 15 digits, starting and ending with 3.")
                        : __("Required for B2B."),
                },
                {
                    fieldname: "commercial_registration_number",
                    fieldtype: "Data",
                    label: __("Commercial Registration Number"),
                    depends_on: b2b,
                },
                {
                    fieldname: "b2b_attachment",
                    fieldtype: "Attach",
                    label: __("Attachment"),
                    depends_on: b2b,
                },
                {
                    fieldname: "allow_duplicate_vat",
                    fieldtype: "Check",
                    label: __("Allow Duplicate VAT (Manager Override)"),
                    default: 0,
                    hidden: can_override ? 0 : 1,
                    depends_on: "eval:doc.buyer_kind === 'B2B (Company)' && doc.tax_id",
                },
                {
                    fieldname: "duplicate_vat_reason",
                    fieldtype: "Small Text",
                    label: __("Duplicate VAT Reason"),
                    hidden: can_override ? 0 : 1,
                    depends_on: "eval:doc.allow_duplicate_vat",
                    mandatory_depends_on: "eval:doc.allow_duplicate_vat",
                },
                // ── Address Details ──────────────────────────────────────────
                {
                    fieldtype: "Section Break",
                    label: __("Address Details"),
                    depends_on: b2b,
                },
                {
                    fieldname: "address_type",
                    fieldtype: "Select",
                    label: __("Address Type"),
                    options: "Billing\nShipping",
                    default: "Billing",
                    depends_on: b2b,
                    mandatory_depends_on: b2b_saudi,
                },
                {
                    fieldname: "address_line1",
                    fieldtype: "Data",
                    label: __("Address Line 1"),
                    depends_on: b2b,
                    mandatory_depends_on: b2b_saudi,
                },
                {
                    fieldname: "address_line2",
                    fieldtype: "Data",
                    label: __("Address Line 2"),
                    depends_on: b2b,
                },
                {
                    fieldname: "custom_building_number",
                    fieldtype: "Data",
                    label: __("Building Number"),
                    depends_on: b2b,
                    mandatory_depends_on: b2b_saudi,
                },
                {
                    fieldname: "district",
                    fieldtype: "Data",
                    label: __("District / Area"),
                    depends_on: b2b,
                    mandatory_depends_on: b2b_saudi,
                },
                {
                    fieldname: "city",
                    fieldtype: "Data",
                    label: __("City"),
                    depends_on: b2b,
                    mandatory_depends_on: b2b_saudi,
                },
                {
                    fieldname: "country",
                    fieldtype: "Link",
                    options: "Country",
                    label: __("Country"),
                    default: company_country,
                    depends_on: b2b,
                    mandatory_depends_on: b2b_saudi,
                },
                {
                    fieldname: "pincode",
                    fieldtype: "Data",
                    label: __("Postal Code"),
                    depends_on: b2b,
                    mandatory_depends_on: b2b_saudi,
                    description: is_saudi ? __("Exactly 5 digits.") : "",
                },
            ],

            primary_action_label: __("Create Customer"),
            primary_action: function (values) {
                var is_b2b = values.buyer_kind === "B2B (Company)";
                var allow_dup = values.allow_duplicate_vat ? 1 : 0;
                var dup_reason = (values.duplicate_vat_reason || "").trim();
                var vat = (values.tax_id || "").trim();

                if (is_saudi && (values.mobile_no || "").replace(/\D/g, "").length < 10) {
                    frappe.msgprint(__("Mobile number must have at least 10 digits."));
                    return;
                }
                if (allow_dup && !can_override) {
                    frappe.msgprint(__("You do not have permission to override the VAT duplicate check."));
                    return;
                }
                if (allow_dup && !dup_reason) {
                    frappe.msgprint(__("Please provide a reason for allowing duplicate VAT."));
                    return;
                }

                if (is_b2b && !vat) {
                    frappe.msgprint(__("VAT Registration Number is required for B2B customers."));
                    return;
                }
                if (is_b2b && !values.b2b_attachment) {
                    frappe.msgprint(__("Please attach the required VAT document for B2B customers."));
                    return;
                }

                if (is_b2b && is_saudi) {
                    if (!/^3\d{13}3$/.test(vat)) {
                        frappe.msgprint(__("VAT must be exactly 15 digits, starting and ending with 3."));
                        return;
                    }
                    if ((values.pincode || "").replace(/\D/g, "").length !== 5) {
                        frappe.msgprint(__("Postal Code must be exactly 5 digits."));
                        return;
                    }
                }

                // VAT duplicate pre-check (skip when overriding)
                if (is_b2b && vat && !allow_dup) {
                    frappe.db
                        .get_value("Customer", { custom_vat_registration_number: vat }, "name")
                        .then(function (res) {
                            if (res.message && res.message.name) {
                                frappe.msgprint(
                                    __("VAT already used by Customer: {0}.", [res.message.name])
                                    + (can_override
                                        ? " " + __("Tick 'Allow Duplicate VAT' to override.")
                                        : "")
                                );
                                return;
                            }
                            do_create();
                        });
                    return;
                }

                do_create();

                function do_create() {
                    frappe.call({
                        method: "vansale.sf_trading.api.customer.create_customer_with_address",
                        args: {
                            customer_name:                values.customer_name,
                            mobile_no:                    values.mobile_no,
                            email_id:                     values.email_id || null,
                            buyer_kind:                   values.buyer_kind,
                            company:                      company,
                            country:                      (is_b2b ? values.country : null) || company_country,
                            default_currency:             default_currency,
                            tax_id:                       is_b2b ? (vat || null) : null,
                            commercial_registration_number: is_b2b ? (values.commercial_registration_number || null) : null,
                            address_type:                 is_b2b ? (values.address_type || null) : null,
                            address_line1:                is_b2b ? (values.address_line1 || null) : null,
                            address_line2:                is_b2b ? (values.address_line2 || null) : null,
                            custom_building_number:       is_b2b ? (values.custom_building_number || null) : null,
                            district:                     is_b2b ? (values.district || null) : null,
                            city:                         is_b2b ? (values.city || null) : null,
                            pincode:                      is_b2b ? (values.pincode || null) : null,
                            attachment:                   is_b2b ? (values.b2b_attachment || null) : null,
                            allow_duplicate_vat:          allow_dup,
                            duplicate_vat_reason:         allow_dup ? dup_reason : null,
                        },
                        callback: function (r) {
                            if (r.message) {
                                frm.set_value(field_name, r.message.customer);
                                frm.refresh_field(field_name);
                                frappe.show_alert({ message: r.message.message, indicator: "green" });
                                d.hide();
                            }
                        },
                    });
                }
            },
        });

        d.show();
        if (company_country) {
            d.set_value("country", company_country);
        }

        // Digit masks
        d.fields_dict.mobile_no.$input.on("input", function () {
            this.value = this.value.replace(/[^0-9]/g, "").slice(0, 15);
        });
        if (is_saudi) {
            d.fields_dict.tax_id.$input.on("input", function () {
                this.value = this.value.replace(/[^0-9]/g, "").slice(0, 15);
            });
            d.fields_dict.pincode.$input.on("input", function () {
                this.value = this.value.replace(/[^0-9]/g, "").slice(0, 5);
            });
        }
    });
}
