# Van Sale — Testing Checklist

Use this before claiming "it works". Grouped by maturity — ✅ tested & stable, ⚠️ partial / known gaps, ❌ not yet wired.

## ✅ Test these — should all work

### Auth
- [ ] Open `/vansale` on mobile → redirect loads → Login form visible
- [ ] Bad credentials → "Incorrect email or password" message
- [ ] Good credentials → PIN setup screen
- [ ] Set PIN (4–8 digits) → dashboard opens
- [ ] Close app → reopen → PIN unlock screen (not re-login)
- [ ] PIN within 2 hour window → skip to dashboard
- [ ] Wrong PIN → "Incorrect PIN" message
- [ ] Log out → full reset, back to login

### Dashboard
- [ ] Shows Van code (e.g. `VAB-AB-001`)
- [ ] Shows default warehouse name
- [ ] Shows currency
- [ ] Today sales / collection tiles render (zero is fine)
- [ ] Tiles: New Invoice / Collect Payment / Customers / Invoices / Today's Route / Van Stock buttons all navigate correctly

### Customer
- [ ] Customer list loads (all active customers for the company)
- [ ] Search filters by name / mobile / VAT
- [ ] Offline: list falls back to cached customers (requires one online open first)

### Invoice creation
- [ ] New Invoice → customer dropdown populated
- [ ] Warehouse shows as fixed single warehouse (picker hidden for one-warehouse configs)
- [ ] Item catalog loads, scoped to the warehouse
- [ ] Tap an item → adds to lines with default qty 1 + standard rate
- [ ] Edit qty / rate inline
- [ ] Remove a line with ✕
- [ ] Submit → redirects to dashboard with success message
- [ ] Invoice appears under `Invoices` list
- [ ] Server-side: doc created with `update_stock=1`, `set_warehouse` = van warehouse, `cost_center` = van cost center

### Payment
- [ ] Collect Payment → customer dropdown populated
- [ ] Pick customer → outstanding invoices listed (if any)
- [ ] Cash / Bank mode selector
- [ ] Amount entered + submit → success
- [ ] Payment Entry created server-side with the van's cost center

### Offline queue
- [ ] Turn off WiFi + mobile data
- [ ] Create invoice → `Saved offline (xxxxxxx) — will sync when online`
- [ ] Sync Badge in header shows `1 offline`
- [ ] Re-enable network
- [ ] Badge auto-drains → `Up to date`
- [ ] Server-side: invoice now exists with correct `posting_time` (the OFFLINE timestamp, not drain time)

### Sync errors
- [ ] If drain fails (e.g. API rejects a queued invoice), the Sync Errors view lists the entry with the server message
- [ ] Retry / Dismiss both work

### Van stock
- [ ] `/van-stock` lists items currently on the van
- [ ] Stock count matches what's in ERPNext's Bin for that warehouse

### Router
- [ ] Deep refresh on `/vansale/#/customers` → still works (hash mode)
- [ ] Android back button / browser back → one level up (not exit)

---

## ⚠️ Partial / rough edges — test but flag

- **Dashboard currency**: uses `session.currency` from `config_defaults`. If a user has no Company default_currency, may show blank.
- **Arabic / RTL**: locale keys exist but not smoke-tested end-to-end.
- **Large item catalog**: pagination stops at 500 items. Real vans shouldn't have more.
- **Price list rate**: uses `Item.standard_rate`. Customer-specific price list selection is TODO.
- **Tax**: if the Company's default tax template references a cost center the van doesn't have access to, `van_defaults.override_cost_center_from_van` rewrites it — but there's no visible warning to the user.
- **Item search by barcode**: backend accepts `search` param. Frontend uses it in InvoiceFormView but no dedicated barcode-scan hook yet (Phase 4 helper exists but isn't wired into the form).

---

## ❌ Not tested / not wired — don't expect to work yet

- **Barcode scanner** on native APK (`@capacitor-mlkit/barcode-scanning` helper exists; no APK built yet)
- **Bluetooth receipt printer** (ESC/POS helper exists; no APK; no invoice-submit hook)
- **Signature capture on invoice submit** (SignaturePad exists, used in RouteVisitView only)
- **GPS breadcrumb during visits** (helper pulls position on visit start/end; continuous polling not implemented)
- **Sales Return** (backend API exists, no frontend view)
- **PDF download** of invoice (helper `saveBlobToDevice` works; no server endpoint producing invoice PDFs yet)
- **ZATCA e-invoice compliance** (KSA QR + compliance fields)
- **Route plan creation UI** for managers (only `route.today` consumption is wired; creating a plan requires desk for now)
- **Van stock transfer** from main warehouse to van (API exists, no frontend)
- **Daily report view** for managers (API exists, no frontend)
- **Capacitor APK** (Phase 5 shell + scripts ready; no keystore generated yet)

---

## How to report a bug

1. What did you try? (user + screen + action)
2. What did you expect? / What did you see?
3. Screenshot if possible
4. Exact time — so I can find the server Error Log entry

I'll check:
- Frappe Error Log (`method LIKE '%vansale%'`, last 30 min)
- Vansale Outbox row (if the action was a write that drained)
- Browser DevTools console (`chrome://inspect` over USB for mobile)
