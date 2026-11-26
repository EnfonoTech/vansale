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
| 10 | An Individual customer could be saved with a VAT number and no address. A VAT buyer gets a standard tax invoice, which ZATCA refuses without the buyer's address. Now the VAT / CR number (and the certificate photo) are on B2B only, and the server refuses a VAT number on a B2C customer in Saudi Arabia. | `9f6e573` | `CustomerFormView.vue` (`isB2B` gates the VAT / CR / photo fields and what is sent); `vansale/api/customer.py` `create` |
| 11 | A new customer's address title kept the name as typed, while the customer name may be saved in Title Case. Now the address title is the saved name. | `9f6e573` | `vansale/api/customer.py` `create`: `"address_title": doc.customer_name` |
| 12 | The customer and address forms always started in Saudi Arabia, so a van of a non-Saudi company got the KSA / ZATCA rules (VAT format, building number, postal code) unless the salesman changed the country. Now they start in the company's country; the address form also applies the B2B address rules to any customer with a VAT number. | `293dfee` | `vansale/api/me.py` `customer_form_config(company)` (`country`); `features/van/ksa.ts` (`defaultCountry`, `countryOptions`); `CustomerFormView.vue`, `AddressFormView.vue` |
| 13 | Invoices, payments and returns took their date from the phone clock: a clock set back made an overdue invoice look younger, and the ZATCA issue date was the phone's. Now online saves send no time and the server dates them; work queued offline keeps its own time only if it is not in the future and not older than 24 h (site config `vansale_offline_grace_hours`), else it is dated on arrival. | 21 Nov | `vansale/api/datetime_util.py` `document_datetime()`, used in `invoice.py`, `payment.py`, `sales_return.py`; `frontend/src/api/invoice.ts`, `payment.ts` (online calls send no `posting_ts`) |
| 14 | Collections took the company from the user's default Company permission (invoices use the van's), listed and auto-matched other companies' invoices, and never sent the cheque / transfer date (it became the payment date). Now the van's company, its invoices only (another company's is refused), and a date field next to the reference. | 21 Nov | `vansale/api/payment.py` `save`, `outstanding`, `_same_company`; `PaymentFormView.vue` |
| 15 | A return against an invoice put the returning salesman in the sales team while the header kept the original sales person. Now it copies the original invoice's sales team, as the desk's return does. | 21 Nov | `vansale/api/sales_return.py` `build_return_against` |
| 16 | The Customer `before_insert` hook added the user's sales person at 100% even when a desk user had already entered another salesman, so ERPNext refused the save ("Total contribution percentage should be equal to 100"). Now it adds one only to a customer with no sales team. | 21 Nov | `vansale/customer_hooks.py` `auto_assign_sales_person` |
| 17 | The CR number field fell back only to `custom_cr_number`; `custom_commercial_registration_number` is now also recognised. | 21 Nov | `vansale/api/me.py` `cr_number_field` |
| 18 | An invoice made from an order with an advance showed and asked for the full total; the server then collected only what was left, so the app told the salesman "paid in full" while asking the customer for too much. Now the advance is shown and the amount asked is the rest. | 21 Nov | `vansale/api/invoice.py` `detail` (`total_advance`); `InvoiceFormView.vue`, `InvoiceDetailView.vue` |
| 19 | Offline / sync safety: queued work tagged with its user and sent only for them (logout counts the real queue, PIN re-sign-in warns); 502/503/504 = network (queued); an ended session sends the user to sign-in; *Retry* clears the backoff; "already exists" is a refusal not success; classification by the server's exception type (Arabic); Dismiss asks first. | 21 Nov | `frontend/src/app/frappe.ts`, `App.vue`, `offline/queue.ts`, `offline/drain.ts`, `offline/classify.ts`, `offline/db.ts`, `views/MoreView.vue`, `PinView.vue`, `SyncErrorsView.vue` |
| 20 | Web app offline start: the service worker keeps the build's files (list from `/vansale/shell-files.json`) and the last page. | 21 Nov | `vansale/pwa.py` (`SW_JS`, `_shell_files`) |
| 21 | Returns: a partly paid invoice is settled first and only the rest refunded; a refund with no mode is refused. | 21 Nov | `vansale/api/sales_return.py` (`_settle_against_original`, `preview` `refund_max`); `RefundSection.vue`, both return views |
| 22 | Drafts: delete works (own drafts, `vansale.api.selling.delete_draft`); one draft invoice per order; a desk draft's line discount not applied twice; discounted rate rounded before the amount; a lead with an ERPNext status can be edited. | 21 Nov | `selling.py`, `sales_order.py`, `lead.py`, `setup.py`; `InvoiceFormView.vue`, `SellingFormView.vue`, `LeadFormView.vue`, `api/invoice.ts`, `api/selling.ts` |
| 23 | Retries keep one client id (new customer / quotation / order / conversions); contact / address Save waits for the load; overpaying invoices refused unless advances are on; route summary and visit buttons; van stock from the van's warehouse with sold-out items; queued sales in the invoice list; the cart kept across "New customer"; an order's advance shown on its invoice. | 21 Nov | `customer.ts`, `selling.ts`, `CustomerFormView.vue`, `ContactFormView.vue`, `AddressFormView.vue`, `payment.py`, `PaymentFormView.vue`, `route.py`, `RouteTodayView.vue`, `van_stock.py`, `InvoiceListView.vue`, `InvoiceFormView.vue` |
| 24 | A refused queued entry is fixed in a form (lines, payment, cheque, amount, notes; raw JSON only under "Advanced"); the sync list refreshes after a send; split cash "tap for rest" fills the amount to pay (less advance / loyalty). | 21 Nov | `EditQueueEntryView.vue`, `SyncErrorsView.vue`, `InvoiceFormView.vue` |

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
| Pre-check before submit (customer gates, overdue credit, ERPNext credit limit) and the setting "Credit sale only for customers with a credit limit" — also: the minimum price checked after the invoice discount (`net_rate`), and returns pre-checked for the customer gates that refuse them (21 Nov) | `080da80` | `vansale/api/precheck.py` (leave out the `steelforce` calls), invoice form |
| Credit panel (limit / used / available / overdue) on the customer screen and in Payment, cached for offline use | `080da80` | customer view, invoice form payment section |
| Help on each line: last price to this customer, a short-stock warning, tap a price to use it, History & stock | `080da80` | `vansale/api/item.py` (`last_sales`, `stock_levels`, `insight`), `features/van/lineInsight.ts`, `components/LineInsight.vue`, invoice form |
| CR number field setting (the Customer field that holds the CR number) | `806fbc8` | Vansale Settings, customer API |
| "Customers a salesman finds" setting: own customers, or own list with a search over every customer the user may see | 21 Nov | Vansale Settings `customer_scope`; `customer.py` `list_mine`; `CustomerListView.vue` |
| Second phone number and document photos from the contact screen | 21 Nov | `customer.py` `save_contact` (`phone_2`), `attach_document`; `ContactFormView.vue` |

## Do not move

- **Lead / Quotation / Sales Order and everything built on them:**
  - lead → quotation → order cycle; the "Quotation becomes" setting; `quotation.make_invoice`
  - Lost reasons and Expired status; request cancellation
  - the lead draft-quotation fix; row links on drafts made from an order or quotation
  - Quotation / Sales Order print formats (`eb2ffef`)
  - Files: `quotation.py`, `sales_order.py`, `selling.py`, `SellingFormView.vue`, `SellingDetailView.vue`
- **"Cash sale collection" setting:** added and then removed on develop_2, so there is nothing to move.
- **Delivery person on cash sales:** this uses sf_trading's `custom_driver`, so it is Steel Force only.
- **Steel Force collections and pricing** (21 Nov): collections / part cheques / loyalty through sf_trading's
  payment function, branch price lists and branch prices, the company print format fallback, own uncollected
  cash, the setup check (`vansale/steelforce/`).
- **Steel Force customer rules** (19 Nov): B2B only for the B2B Creator role, duplicate name refused, mobile and
  VAT photo required on the server, the photo filed on the VAT Certificate row, the 10-digit mobile rule for a
  Saudi company only (`mobile_min_digits`). All in
  `vansale/steelforce/` and `customer_form.b2b`; on a standard site `can_create_b2b()` is always true.
- **Everything tagged [SF] and all of `vansale/steelforce/`.**

## Keep this list current

When a new [STD] fix lands on `develop_2`, add a row here. When a row is moved to `develop`, mark it with the
`develop` commit, e.g. `→ develop abc1234`.
