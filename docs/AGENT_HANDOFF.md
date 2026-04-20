# Van Sale — Agent Handoff

> **Start here if you're a fresh agent picking up this repo.**
> As of 2026-04-20 P1–P5 + feedback phases A–E all live on `trading-demo.enfonoerp.com`.
> Phase plans in [`superpowers/plans/`](superpowers/plans/).

---

## 1. What this project is

Offline-first van-sales PWA on Frappe v15 + ERPNext. One Vue 3 source
tree ships as both a web PWA (at `/vansale`) and a signed Capacitor
Android APK (scripts in place; keystore to be generated per customer).
Replaces the existing `fateh_pwa` React PWA — same domain, new spine
that inherits every lesson from the Fateh HR rebuild.

**Architecture source of truth:** `~/.claude/skills/frappe-vue-pwa/SKILL.md`.
**Infra + deploy source of truth:** `~/.claude/skills/enfono-servers/SKILL.md`.
**Mirror pipeline:** `~/.claude/skills/fatehhr/SKILL.md`.

---

## 2. Current state

| Thing | Value |
|---|---|
| Repo | https://github.com/EnfonoTech/vansale (public, branch `develop`) |
| PWA URL | https://trading-demo.enfonoerp.com/vansale |
| Site | `trading` on GS DEV (`94.136.186.151`, bench user `v15`) |
| Server ID | `8d69b825-6148-4da6-817b-d079a37f422d` |
| App | `vansale` (module `Vansale`) |
| DocTypes live | Vansale Pin, Vansale Outbox, Van Route Plan, Van Route Stop, Van Visit Log, **Vansale Configuration** (+ 3 child tables) |
| Roles | **Van User**, **Van Manager** (auto-created via `setup.after_migrate`) |
| Custom fields | `Sales Invoice.custom_client_id`, `Payment Entry.custom_client_id` |
| Frontend `NATIVE_VERSION` | `1.0.0` / code 1 (bumped via `scripts/bump-version.mjs`) |
| APK | Not yet built — keystore generation is a one-liner when first customer is picked |

### Phases shipped

- **P1 Foundation** — Frappe app scaffold, PIN auth (bcrypt + stable api_secret), CORS, Vue 3 + Pinia + vue-router + vue-i18n SPA skeleton, theme plugin.
- **P2 Offline engine** — IDB schema (9 stores), queue, ordered drain (photos → invoices → payments → returns → visits), ONE-uploader `capturePhoto` / `resolveToRealUrl`, `SignaturePad`, `PhotoSlot`, `SyncBadge`, `SyncErrorsView`, `UTC-ISO` datetime helpers, `file_upload` endpoint, `Vansale Outbox` audit DocType.
- **P3 Core sales flow** — API for customer / item / invoice / payment / sales return / dashboard (today sales + collection + recent activity + month summary + warehouses); Vue views: Dashboard, CustomerList, InvoiceList, InvoiceForm, PaymentForm. Every write is idempotent by `client_id` so drain retries are safe.
- **P4 Van-specific** — Van Route Plan + Stop + Visit Log DocTypes; `route.today/start_visit/end_visit/daily_report` API; `van_stock.list_stock/transfer_in` using ERPNext Bin (no parallel ledger); scanner / printer / GPS feature helpers (lazy-import Capacitor plugins); `RouteTodayView`, `VanStockView`.
- **P5 Capacitor shell** — `android-capacitor/` with package.json, vite.config.ts, capacitor.config.ts, index.html, src symlink to ../frontend/src; route-hierarchy native back button; `@capacitor/filesystem`-based `saveBlobToDevice`; `bump-version.mjs` (atomic), `_patch-build-gradle.py`, `generate-customer-assets.mjs`, `generate-keystore.sh`, `build-customer.sh` (one-shot).

### Feedback phases (2026-04-20 — from user PDF test list)

- **A UI redesign + runtime fixes** — design-system tokens, icon set (28), 5-tab bottom nav (Home/Route/Sales/Customers/More), toast store, redesigned every view; auto-apply Company default Sales Taxes Template on invoice; v15 Payment Entry explicit `paid_from_account_currency`/`paid_to_account_currency`/`party_account`; `naive_site_to_utc_iso` accepts `str`; CustomerDetailView rewired.
- **B Invoice form overhaul** — `item.detail` returns `uoms[]` with per-UOM price_list_rate via Customer→CustomerGroup→Selling Settings chain; `item.price_for` for UOM change; `invoice.save` accepts per-line `uom`/`conversion_factor`/`price_list_rate`/`discount_percentage`, invoice-level `discount_amount`/`apply_discount_on`, `payment_type` + `mode_of_payment` (auto-adds payments row for Cash + Mode of Payment default account), auto-tags `sales_team` via Vansale Configuration User `sales_person` field. Frontend: catalog click = new line (same-item multi-row), UOM select per line, editable rate with price-list display, discount% per line, Cash/Credit toggle, Save Draft / Save & Submit.
- **C Customer create** — `customer.create` extended with `customer_type` ("b2b"|"b2c"), email, address fields; B2B requires `address_line1` + `city`; creates Address doc + links as primary. `CustomerFormView.vue` + route `customer-new`; inline "New" link from InvoiceFormView + CustomerListView, redirect query back to invoice.
- **D Print + statement** — auto-print popup after submit via `/printview?trigger_print=1`; clickable recent invoices on CustomerDetailView (fixes PDF §3); `customer.statement_html` endpoint (opening GL balance → FIFO ledger of invoices + payments → closing balance), served inline via `display_content_as="inline"`.
- **E Payment FIFO** — `payment.save` accepts `invoice_names: list[str]` for multi-pick; when neither `invoice_name` nor list supplied, auto-allocates FIFO across all outstanding invoices oldest-first; leftover beyond total outstanding remains unallocated (customer credit). `PaymentFormView.vue` multi-select with checkboxes, total outstanding header, FIFO hint when none picked.

### Admin follow-ups (not code)

- Set `sales_person` on the Vansale Configuration User row for each van user so commission auto-tag fires on invoice save.
- Verify `ksa_compliance` hook attaches ZATCA QR on Sales Invoice submit — print via `/printview?doctype=Sales%20Invoice&name=<name>&format=Standard` and confirm QR renders.

### Smoke test results (post-deploy)

```
curl https://trading-demo.enfonoerp.com/vansale                               → 301 → /assets/vansale/spa/index.html
curl https://trading-demo.enfonoerp.com/assets/vansale/spa/index.html          → 200
curl POST /api/method/vansale.api.auth.login                                   → ValidationError (whitelisting works)
curl /api/method/vansale.api.util.version_compat                               → {"min":"1.0.0","current":"1.0.0"}
curl /api/method/vansale.api.util.get_csrf_token                               → 56-char hex (CSRF works)
```

---

## 3. How to deploy an update

### Web PWA (one curl)

```bash
cd /Users/sayanthns/ERP\ -\ PWAs/vansale/frontend
CUSTOMER_BUILD_TARGET=web pnpm exec vite build
cd ../vansale/public/spa && tar czf /tmp/vansale-dist.tar.gz --exclude='.DS_Store' .
gh release upload frontend-dev --repo EnfonoTech/vansale /tmp/vansale-dist.tar.gz --clobber

# Server: pull code + download tarball + signal workers
curl -s -X POST "http://207.180.209.80:3847/api/servers/8d69b825-6148-4da6-817b-d079a37f422d/command" \
  -H "Authorization: Bearer 9c9d7e54d54c30e9f264f202376c04ed4dd4bab9c57eb2b3" \
  -H "Content-Type: application/json" \
  -d '{"command":"set -e; cd /home/v15/frappe-bench/apps/vansale && sudo -u v15 git pull --ff-only && cd /tmp && curl -fsSL -o vansale-dist.tar.gz https://github.com/EnfonoTech/vansale/releases/download/frontend-dev/vansale-dist.tar.gz && sudo -u v15 rm -rf /home/v15/frappe-bench/apps/vansale/vansale/public/spa && sudo -u v15 mkdir -p /home/v15/frappe-bench/apps/vansale/vansale/public/spa && sudo -u v15 tar xzf /tmp/vansale-dist.tar.gz -C /home/v15/frappe-bench/apps/vansale/vansale/public/spa && cd /home/v15/frappe-bench && sudo -u v15 bench build --app vansale && sudo supervisorctl signal QUIT frappe-bench-web:frappe-bench-frappe-web && sudo supervisorctl signal QUIT frappe-bench-workers:frappe-bench-frappe-long-worker-0 && sudo supervisorctl signal QUIT frappe-bench-workers:frappe-bench-frappe-short-worker-0 && echo DEPLOYED"}'
```

Backend (Python) changes: as above plus `bench --site trading migrate` if DocTypes / fixtures changed.

### Android APK (when a customer is picked)

```bash
cp customers/.env.example customers/.env.demo   # fill in APP_ID, THEME_PRIMARY, etc.
bash scripts/generate-keystore.sh demo           # ONCE — backs password file into ~/.vansale-demo-keystore-pw
bash scripts/build-customer.sh demo              # bumps version → web tarball → cap copy → patch gradle → assembleRelease

# Artefacts:
dist/vansale-demo-1.0.1.apk
dist/vansale-demo-pwa.tar.gz
```

---

## 4. Local dev loop

```bash
cd frontend
pnpm install
pnpm dev            # Vite on :8082 proxying /api → localhost:8000
pnpm type-check     # vue-tsc --noEmit
pnpm build          # → ../vansale/public/spa/
```

Set `VITE_API_BASE` in `frontend/.env.local` for native builds; web uses same-origin.

---

## 5. Smoke test kit

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://trading-demo.enfonoerp.com/assets/vansale/spa/index.html
curl -s https://trading-demo.enfonoerp.com/api/method/vansale.api.util.version_compat
curl -s https://trading-demo.enfonoerp.com/api/method/vansale.api.util.get_csrf_token

# With auth cookie/token:
curl -s https://trading-demo.enfonoerp.com/api/method/vansale.api.customer.list_mine -H "Cookie: ..."
curl -s https://trading-demo.enfonoerp.com/api/method/vansale.api.dashboard.today_sales -H "Cookie: ..."
```

---

## 6. Creating a Van User

Mirrors RMAX's Branch Configuration pattern. One `Vansale Configuration` row per van; add the user as a child row and the controller auto-creates their User Permissions + assigns the role.

1. Desk → **Vansale Configuration** → **New**.
2. `Van Code` = stable identifier, e.g. `VAN-RIYADH-01`.
3. `Company` (required), `Branch` (optional).
4. Warehouse table — add one row per warehouse the van can draw from. **First row = user's default warehouse.**
5. Cost Center table — add one row per cost center. **First row = user's default cost center.**
6. User table — add the Frappe User + role (`Van User` by default).
7. Save. Behind the scenes:
   - User Permissions written: Company (`is_default=1`), first Warehouse (`is_default=1`), first Cost Center (`is_default=1`), plus the Company's default cost center so tax templates resolve.
   - `Van User` role assigned to the user.
   - On PIN unlock, the PWA calls `vansale.api.me.config_defaults` and caches the defaults in localStorage; the invoice form pre-fills warehouse + hides the picker when there's only one.
8. **⚠️ Set a password** for each added user. Frappe's default "new user email" often fails on demo tenants (email queue unconfigured), which leaves the account with no password at all. Without a password the PWA login rejects them and they see what looks like an "empty screen".

   **Option A — User doc**: open the User record → Password field → set one.

   **Option B — API (bulk)**:
   ```bash
   curl -X POST https://<site>/api/method/vansale.api.admin.set_user_password \
     -H "Authorization: token <admin-key>:<admin-secret>" \
     -H "Content-Type: application/json" \
     -d '{"user":"driver1@example.com","new_password":"VanUser@123"}'
   # List users missing passwords:
   curl https://<site>/api/method/vansale.api.admin.users_without_password \
     -H "Authorization: token <admin-key>:<admin-secret>"
   ```

   The admin endpoint is gated to users listed in at least one Vansale Configuration, so it can't be used as a general password reset.

Cost centers and warehouses on new Sales Invoice / Payment Entry / Delivery Note / Stock Entry rows are rewritten by `van_defaults.override_*` before validate — so even if somebody edits the payload, the doc lands on the user's default.

List views (Sales Invoice, Payment Entry, Stock Entry, Delivery Note, Van Visit Log, Van Route Plan) are filtered by `vansale.van_filters.*` — van users only see rows touching their warehouse(s).

## 7. Forensic debug loop (when users report stuck sync)

Same as fatehhr §6 — always check in this order, never ship a speculative fix without step 3:

1. Ask user for Settings → Version.
2. Check server doc state via bench console (`frappe.get_doc("Sales Invoice", ...)`).
3. Check Frappe Error Log — last 30 min, method LIKE `%vansale%`.
4. Check client Sync Errors view — `attempts >= 1` surfaces server rejection verbatim.
5. chrome://inspect → IndexedDB + Console if 1–4 don't explain it.

---

## 7. Known gotchas carried over

Read `frappe-vue-pwa` §5 for the full 20 commandments. The ones most likely to bite Van Sale specifically:

- `allow_cors` on `trading` was already `"*"` so `ensure_capacitor_cors` is a no-op — fine, but don't strip CORS in a future hardening pass without also adding the Capacitor origins back (§3.6).
- Sales Team filter in `customer.list_mine` returns *all* customers if the user has no Sales Person record. Good for demo; tighten in P3.5 if stricter scoping is needed.
- Van stock uses ERPNext Bin; the user needs a default `Warehouse` or `Sales Person.custom_van_warehouse`. Without it, VanStockView shows "No van warehouse set."
- Default Mode of Payment: `payment.save` assumes Cash/Bank with a Mode of Payment Account on the Company. If the `trading` site is missing those, payments fail with "Could not resolve accounts." — set defaults on Company first.

---

## 8. Open items

- [ ] Generate demo keystore + first APK (run `bash scripts/generate-keystore.sh demo` + `bash scripts/build-customer.sh demo`).
- [ ] Seed demo data on `trading`: salesperson user, a couple of van warehouses, items with prices, a few customers, a route plan for today.
- [ ] Add `~/.claude/skills/vansale/SKILL.md` (mirror of `fatehhr` skill, swap infra IDs + paths).
- [ ] Optional hardening: tighten customer scoping per Sales Team, add real-time via socket.io, add PDF print for invoices.

---

## 9. Pair skills

- **`frappe-vue-pwa`** — architecture source of truth.
- **`enfono-servers`** — server inventory, SSH/API, safety rules, maintenance window.
- **`fatehhr`** — mirror deploy pipeline (swap paths + app id).

Read all three before any substantive change.
