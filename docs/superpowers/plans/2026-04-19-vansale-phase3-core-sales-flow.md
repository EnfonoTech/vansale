# Van Sale — Phase 3: Core Sales Flow (Offline-First) — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development / superpowers:executing-plans.
>
> **Inherit rules from Phases 1–2 + `frappe-vue-pwa` skill.** No exceptions.

**Goal:** Ship the day-to-day van salesman flow end-to-end with offline-first behaviour: browse cached customers + items, create sales invoice (with stock update), collect payment, record sales return, view today's sales + collection. Uses the Phase 2 queue + drain spine; no domain-specific offline infrastructure.

**Architecture:** Reuse ERPNext core doctypes (Customer, Item, Sales Invoice, Payment Entry, Sales Invoice Return). Mirror `fateh_pwa/pwa.py` endpoint shape where sensible, but trim to what's needed and enforce UTC-ISO on every datetime return. One Pinia store per domain, each wiring `saveXxx` through the §4.2 golden template.

**Tech:** Frappe + ERPNext v15; Vue 3 + Pinia; idb for caches.

---

## Endpoint inventory (new `vansale/api/`)

| File | Endpoints | Notes |
|---|---|---|
| `customer.py` | `list_mine`, `detail`, `create`, `summary`, `addresses`, `create_address`, `update_address` | Salesperson → customers map via `Sales Team` or user → `Sales Person` |
| `item.py` | `list_mine`, `detail`, `stock_balance`, `price`, `search` | Includes per-warehouse stock; cached client-side |
| `invoice.py` | `list_mine`, `detail`, `save` (idempotent by `client_id`), `cancel` | `save` accepts client UTC-ISO posting_date; uses `update_stock=1` |
| `payment.py` | `list_mine`, `detail`, `save_cash`, `save_bank`, `outstanding` | Links to Sales Invoice; submits Payment Entry |
| `sales_return.py` | `list_mine`, `detail`, `save`, `submit`, `reasons` | Validates against original invoice |
| `dashboard.py` | `today_sales`, `today_collection`, `month_summary` | All timestamps UTC-ISO |

Every endpoint returns datetimes via `naive_site_to_utc_iso` (Phase 2). Every endpoint uses `ApiError`-style `frappe.throw` so the client path correctly distinguishes from network failures.

---

## Tasks

### Task 1 — Customer endpoints + cache

- [ ] Write `vansale/api/customer.py` — `list_mine(limit, search?)` returns assigned customers for logged-in salesperson (derive via `Sales Team` child of Customer or `Sales Person.user = frappe.session.user`). `detail(name)` includes addresses, outstanding, last-3 invoices. `create(payload)` with English + Arabic name, VAT, territory, address child. `summary(customer)` for AR tile.
- [ ] Frontend: `src/api/customer.ts`, `src/stores/customer.ts`, `src/views/CustomerListView.vue`, `CustomerDetailView.vue`, `CustomerFormView.vue`. Cache list in `customer_cache` store; optimistic offline create queues to `customer_queue` (drained before invoices).
- [ ] **Commit** `feat(customer): offline-first customer CRUD`.

### Task 2 — Item endpoints + catalog

- [ ] Write `vansale/api/item.py` — `list_mine(limit, filters?, warehouse?)` returns items saleable for the user's company, with `stock_balance` per warehouse; `detail` includes price list rate + tax; `search(q)` used by the invoice screen.
- [ ] Frontend: item cache + `ItemCatalogView.vue`, used as a bottom-sheet picker in the invoice form.
- [ ] Thumbnails: reuse `PhotoSlot` thumbnail cache; download with `absoluteUrl()` on native (§4.8).
- [ ] **Commit** `feat(item): catalog + stock lookup + offline cache`.

### Task 3 — Sales invoice flow

- [ ] Write `vansale/api/invoice.py`:
  - `save(payload)` — accepts `client_id` (UUID) for idempotency: if a row on `Sales Invoice.custom_client_id = client_id` exists, return that doc. Otherwise create + submit (or leave draft per flag). `update_stock=1`. Posting_date from `parse_client_ts(payload.posting_time_iso)`.
  - `submit(name)`, `cancel(name)`, `detail(name)`, `list_mine(limit, date_range?)`.
- [ ] Add custom field `Sales Invoice.custom_client_id` via `fixtures/custom_field.json`.
- [ ] Frontend: `src/offline/processors/invoice.ts` (full — replacing P2 stub). `src/views/InvoiceFormView.vue`: customer picker → item picker → qty/price/discount → tax auto-calc → save.
- [ ] Integration test: create invoice offline → drain → server has one Sales Invoice, correct posting time, stock decremented.
- [ ] **Commit** `feat(invoice): idempotent save + offline submit pipeline`.

### Task 4 — Payment Entry flow

- [ ] Write `vansale/api/payment.py` — `save_cash(invoice, amount, reference_no?)`, `save_bank(invoice, amount, bank_account, reference_no)`, `outstanding(customer)`. `client_id` idempotency like invoices. Mode of Payment resolved from site default (fallback to `Cash`).
- [ ] Frontend: `PaymentFormView.vue` launched from invoice detail or AR list. Queue processor + drain.
- [ ] **Commit** `feat(payment): offline cash/bank payment flow`.

### Task 5 — Sales return flow

- [ ] Write `vansale/api/sales_return.py` — `save(original_invoice, items[], reason)` builds return Sales Invoice `is_return=1 return_against=<orig>`. Validates qty not exceeding original.
- [ ] Custom fixture: `Sales Invoice Item.custom_return_reason` (Link to Reason doctype) — or plain data field for P3; P4 formalises reasons.
- [ ] Frontend: `SalesReturnFormView.vue` with scan-invoice / pick-items / qty entry.
- [ ] **Commit** `feat(return): offline sales return flow`.

### Task 6 — Dashboard

- [ ] Write `vansale/api/dashboard.py` — `today_sales()` (sum of Sales Invoice grand_total where posting_date = today for user's salesperson), `today_collection()` (sum of Payment Entry paid_amount), `month_summary(month)`. All datetimes UTC-ISO.
- [ ] Frontend: `DashboardView.vue` replaces the P1 stub — four KPI tiles, last-5 activity, pending sync badge.
- [ ] **Commit** `feat(dashboard): today sales + collection tiles`.

### Task 7 — Pricing + tax consistency

- [ ] Verify price list rate on offline save matches online re-pricing on drain (so customers don't see a different total post-sync). Strategy: snapshot `price_list_rate`, `tax_rate`, `currency` into the queue payload; server trusts the snapshot if within 24h, otherwise re-prices + returns a `price_drift` warning.
- [ ] **Commit** `feat(pricing): snapshot-based offline pricing with drift detection`.

### Task 8 — i18n

- [ ] English + Arabic `locales/*.json` covering all P3 views.
- [ ] RTL flip on `ar` locale (root `dir="rtl"`).
- [ ] **Commit** `feat(i18n): Arabic + RTL support`.

### Task 9 — PDF download skeleton (full wiring in P5)

- [ ] Write `vansale/api/pdf.py` — `get_invoice_pdf(name)` returns bytes. Same pattern as fatehhr payslip (lesson #10).
- [ ] Frontend: `saveBlobToDevice()` from P1 frappe.ts — on web, anchor download; on native, Filesystem (P5 wires this fully).
- [ ] **Commit** `feat(pdf): sales invoice + payment receipt PDFs`.

### Task 10 — Tests + QA loop

- [ ] 80%+ coverage on offline/processors/*.
- [ ] End-to-end: seed demo tenant with 3 customers + 10 items → invoice offline → payment offline → return → drain → verify server state.
- [ ] **Commit** `test: core sales flow coverage`.

### Task 11 — Handoff

- [ ] Update `docs/AGENT_HANDOFF.md` with endpoint inventory + demo tenant seed script.
- [ ] Update `docs/LESSONS_LEARNED.md` — any new gotchas discovered.
- [ ] **Commit** `docs: phase 3 handoff update`.

---

## Exit criteria

- A user can, fully offline: pick a customer, create an invoice, collect payment, capture a return, reopen the app, land online, and see everything drain to server without errors.
- `fateh_pwa` parity for the 80% day-to-day flow; Phase 4 adds van-specific features.
- No naive datetimes returned by any endpoint (server test enforces).
