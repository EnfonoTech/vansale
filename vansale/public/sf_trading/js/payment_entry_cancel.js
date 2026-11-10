// Cancelling a Payment Entry must not demand the Payment Advice behind it be cancelled too.
//
// The advice is the instruction to pay; the Payment Entry is the payment. Cancelling the
// payment leaves the instruction standing so a fresh entry can be raised against it, which is
// what api/payment_advice_hooks.on_payment_entry_cancel does — it clears `payment_entry` and
// puts the advice back to Approved.
//
// The form never let that happen. savecancel() asks the server which submitted documents link
// to this one BEFORE it calls cancel at all (frappe form.js: get_submitted_linked_docs), finds
// the advice, and offers "Cancel All" — which cancels the advice first. The advice then refuses,
// because its own on_cancel will not let it go while a submitted Payment Entry still points at
// it. Neither order worked, and the payment could not be cancelled from the desk.
//
// frappe reads this list in savecancel() for exactly this case. With the advice on it the
// dialog never appears, the Payment Entry cancels on its own, and the hook releases the advice.
// The server is unaffected either way: check_no_back_links_exist runs after on_cancel, by which
// point the advice no longer points anywhere.
frappe.ui.form.on("Payment Entry", {
	onload(frm) {
		frm.ignore_doctypes_on_cancel_all = frm.ignore_doctypes_on_cancel_all || [];
		if (!frm.ignore_doctypes_on_cancel_all.includes("Payment Advice")) {
			frm.ignore_doctypes_on_cancel_all.push("Payment Advice");
		}
	},
});
