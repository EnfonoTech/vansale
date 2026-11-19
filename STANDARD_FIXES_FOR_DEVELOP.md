# Standard fixes to move from `develop_2` to `develop`

`develop_2` is the Steel Force line. Every change there is tagged **[STD]** (right for every client) or
**[SF]** (Steel Force only, in `vansale/steelforce/`). This file lists the [STD] work that `develop`
(the standard app other clients run) still needs.

**`develop` has no Lead, Quotation or Sales Order, and does not need them.** Anything for that selling
flow stays on `develop_2`, even when it is tagged [STD]. See "Do not move" below.

Checked against `upstream/develop` at `973e5b5` on 18 Nov 2026: every fix in part A is still missing there.

## How to move them

- **Copy the change by hand; don't cherry-pick.** The develop_2 commits mix [STD], [SF] and selling-flow
  changes in the same files, so a cherry-pick would bring Steel Force and quotation code into `develop`.
- **Where a shared file also calls quotation / order code, leave those calls out.**
- **Keep the fallbacks.** A site with no Vansale Configuration row must behave as before.
- **Test on a site that runs `develop`, then rebuild and migrate it.**
  - Frontend files change, so run `bench build --app vansale`.
  - `doc_defaults` adds no fields, but run migrate anyway.

## A. Fixes: move all

| # | What was wrong → what it does now | develop_2 commit | Where |
|---|---|---|---|
| 1 | Queued offline sales did not send by themselves. Now they sync on app start, on reconnect, on Android resume and when the tab comes back into view. | `080da80` | `frontend/src/app/App.vue`: `syncPending()` (runs `sync.refresh()`, then `requestDrain()` if anything is pending), called from those four places |
| 2 | After a login with no PIN, the app ran without its settings until the next start. Now the settings load before the dashboard opens. | `080da80` | `frontend/src/views/LoginView.vue`: `await session.refreshDefaults()` before `router.replace({ name: "dashboard" })` |
| 3 | A double tap on Submit made two invoices. Now Submit locks on the first tap. | `080da80` | `frontend/src/views/InvoiceFormView.vue` `doSave()` and `InvoiceDetailView.vue` `submitInvoice()`: set `busy` before the first `await`, and reset it on every early return |
| 4 | Collections always posted to the company's default receivable account. Now they use the customer's own account. | `080da80` | `vansale/api/payment.py` `build_payment_entry`: `paid_from = get_party_account("Customer", customer, company) or receivable` |
| 5 | The customer could be changed while editing a draft invoice. Now it is locked. | `080da80` | `frontend/src/views/InvoiceFormView.vue`: customer `SearchSelect` gets `:disabled="isEditMode"` |
| 6 | The site root `/` showed the van app's login to Administrator, who holds every role. Now desk admins go to `/app` and van users to `/vansale` (302). | `080da80` | `vansale/www/vansale.py`: `_leave_site_root()` |
| 7 | Vansale Configuration pickers listed other companies' warehouses, cost centers and so on. Now they show only the van's company. | `eb2ffef` | `vansale_configuration.js`: `vansale_filter_by_company()` |
| 8 | A site with no price list in Selling Settings could not save a sale. Branch and `custom_sales_person` were also left empty. Now all three are filled before save, but only where they are empty. | `806fbc8` | New `vansale/api/doc_defaults.py` `apply_van_defaults()`. Call it from `invoice.py` and `sales_return.py` only |
| 9 | Warehouse, cost center, branch and company came only from the user's default User Permission, which another app's Branch Configuration can reset. Now the van is read first, then the User Permission. | `806fbc8` | `vansale/api/me.py` `van_default()`, used in `invoice.py`, `item.py`, `van_defaults.py`. Not the `steelforce/` uses |
| 10 | An Individual customer could be saved with a VAT number and no address. A VAT buyer gets a standard tax invoice, which ZATCA refuses without the buyer's address. Now the VAT / CR number (and the certificate photo) are on B2B only, and the server refuses a VAT number on a B2C customer in Saudi Arabia. | `85adc7d` | `CustomerFormView.vue` (`isB2B` gates the VAT / CR / photo fields and what is sent); `vansale/api/customer.py` `create` |
| 11 | A new customer's address title kept the name as typed, while the customer name may be saved in Title Case. Now the address title is the saved name. | `85adc7d` | `vansale/api/customer.py` `create`: `"address_title": doc.customer_name` |

Details for fix 7:

- **Warehouse and cost center:** only the van's company, with no group and no disabled entries.
- **Modes of payment:** only those that have an account for the company.
- **Branch:** filtered only when Branch has `custom_company` (ksa_compliance adds it). Branches with no company set stay in the list.
- **Selling price list:** only enabled selling price lists.

## B. Standard features: move only if wanted

These are new behaviour, not fixes. Each defaults to the old behaviour.

| Feature | develop_2 commit | Where |
|---|---|---|
| "Invoice updates stock" setting (also per van). Off = order taker: no stock moves, and the catalog search covers the whole catalog. | `806fbc8`, `080da80` | Vansale Settings / Configuration, `me.py` `selling_flow`, `searchItems` passing `session.updateStock` |
| Pre-check before submit (customer gates, overdue credit, ERPNext credit limit) and the setting "Credit sale only for customers with a credit limit" | `080da80` | `vansale/api/precheck.py` (leave out the `steelforce` calls), invoice form |
| Credit panel (limit / used / available / overdue) on the customer screen and in Payment, cached for offline use | `080da80` | customer view, invoice form payment section |
| Help on each line: last price to this customer, a short-stock warning, tap a price to use it, History & stock | `080da80` | `vansale/api/item.py` (`last_sales`, `stock_levels`, `insight`), `features/van/lineInsight.ts`, `components/LineInsight.vue`, invoice form |
| CR number field setting (the Customer field that holds the CR number) | `806fbc8` | Vansale Settings, customer API |

## Do not move

- **Lead / Quotation / Sales Order and everything built on them:**
  - lead → quotation → order cycle; the "Quotation becomes" setting; `quotation.make_invoice`
  - Lost reasons and Expired status; request cancellation
  - the lead draft-quotation fix; row links on drafts made from an order or quotation
  - Quotation / Sales Order print formats (`eb2ffef`)
  - Files: `quotation.py`, `sales_order.py`, `selling.py`, `SellingFormView.vue`, `SellingDetailView.vue`
- **"Cash sale collection" setting:** added and then removed on develop_2, so there is nothing to move.
- **Delivery person on cash sales:** this uses sf_trading's `custom_driver`, so it is Steel Force only.
- **Steel Force customer rules** (19 Nov): B2B only for the B2B Creator role, duplicate name refused, mobile and
  VAT photo required on the server, the photo filed on the VAT Certificate row. All in
  `vansale/steelforce/` and `customer_form.b2b`; on a standard site `can_create_b2b()` is always true.
- **Everything tagged [SF] and all of `vansale/steelforce/`.**

## Keep this list current

When a new [STD] fix lands on `develop_2`, add a row here. When a row is moved to `develop`, mark it with the
`develop` commit, e.g. `→ develop abc1234`.
