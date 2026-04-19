# Van Sale — Phase 1: Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox `- [ ]` syntax.
>
> **Source of truth for patterns:** `~/.claude/skills/frappe-vue-pwa/SKILL.md`. Do not duplicate code — follow the skill.

**Goal:** Stand up a fresh Frappe app `vansale` alongside ERPNext on a dev site, with Vue 3 + Pinia + vue-router + vue-i18n + idb SPA skeleton, PIN auth + stable `api_secret`, CORS, deploy pipeline skeleton. Online-only this phase.

**Architecture:** Single `vansale` Frappe v15 app + Vue 3 SPA served at `/vansale`. Auth: email/pwd → set PIN → server stores bcrypt hash → PIN unlock returns stable `api_key`/`api_secret`. Web-only in P1 (native shell = P5). Currency/locale neutral (SAR default; override via env).

**Tech stack:** Frappe v15, ERPNext v15, Python 3.10+, MariaDB 10.11; Vue 3, Pinia, vue-router, vue-i18n, Vite 5, idb, bcrypt; Node 20+, pnpm. Reference: `frappe-vue-pwa` §3.

**Companion skills:** `frappe-vue-pwa` (all §3/§4/§5), `enfono-servers` (deploy), `fatehhr` (deploy pipeline mirror).

---

## Directory layout created in Phase 1

```
vansale/                                      # top-level repo
├── vansale/                                  # Frappe app (bench new-app vansale)
│   ├── hooks.py                              # after_migrate → ensure_capacitor_cors, website_redirects
│   ├── install.py                            # ensure_capacitor_cors()
│   ├── modules.txt                           # "Vansale"
│   ├── patches.txt
│   ├── fixtures/
│   │   └── custom_field.json
│   ├── api/
│   │   ├── __init__.py
│   │   ├── auth.py                           # login, setup_pin, login_with_pin, ping, change_pin
│   │   └── util.py                           # version_compat, get_csrf_token
│   ├── utils/
│   │   ├── __init__.py
│   │   └── secrets.py                        # stable api_secret helper
│   ├── doctype/
│   │   └── vansale_pin/                      # "Vansale Pin" (user, pin_hash, created_at)
│   └── public/
│       └── spa/                              # Vite output lands here after deploy
├── frontend/                                 # Vue 3 SPA
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── .env.example
│   ├── .gitignore
│   ├── plugins/
│   │   └── vite-theme-plugin.ts              # reads CUSTOMER_* env → CSS vars + manifest
│   └── src/
│       ├── main.ts
│       ├── app/
│       │   ├── App.vue
│       │   ├── router.ts                     # hash on native, history("/vansale/") on web
│       │   ├── platform.ts                   # isNative(), API_BASE
│       │   ├── frappe.ts                     # apiCall, loginWithPin, saveBlobToDevice
│       │   └── i18n.ts
│       ├── api/
│       │   ├── client.ts
│       │   └── auth.ts
│       ├── stores/
│       │   └── session.ts
│       ├── views/
│       │   ├── LoginView.vue
│       │   ├── PinView.vue
│       │   └── DashboardView.vue            # stub: shows user name + env
│       ├── components/
│       │   └── TopAppBar.vue
│       └── styles/
│           ├── tokens.css
│           └── base.css
├── scripts/
│   ├── build-customer.sh                     # stub in P1; fully wired in P5
│   └── bump-version.mjs                      # stub in P1
├── docs/
│   ├── AGENT_HANDOFF.md                      # thin now, grows each phase
│   ├── LESSONS_LEARNED.md
│   └── superpowers/
│       ├── plans/                            # this file lives here
│       └── specs/
├── customers/
│   └── .env.example
├── .gitignore
├── README.md
├── pyproject.toml
└── license.txt
```

---

## Tasks

### Task 1 — Project skeleton + git init

- [ ] **Step 1: Create repo root + top-level files** — `/Users/sayanthns/ERP - PWAs/vansale/`. Write `README.md`, `license.txt` (MIT), `.gitignore` (see frappe-vue-pwa §10 for excluded artefact list; add `frontend/dist/`, `*.apk`, `*.keystore`, `.vue.js`, `.tsbuildinfo`, `__pycache__`, `node_modules/`).
- [ ] **Step 2:** `git init && git branch -M develop`.
- [ ] **Step 3: Commit** `chore: initialize vansale repo skeleton`.

### Task 2 — Frappe app scaffold (local-only in this phase)

- [ ] **Step 1:** Write `pyproject.toml` (app_name `vansale`, title `Van Sale`, publisher `Enfono Technologies`, license MIT).
- [ ] **Step 2:** Write `vansale/__init__.py` (version `0.0.1`), `vansale/modules.txt` = `Vansale`, `vansale/patches.txt` (empty).
- [ ] **Step 3:** Write `vansale/hooks.py` with:
  - `app_name`, `app_title`, `app_publisher`, etc.
  - `after_migrate = ["vansale.install.ensure_capacitor_cors"]`
  - `website_redirects = [{"source": "/vansale", "target": "/assets/vansale/spa/index.html"}]`
- [ ] **Step 4:** Write `vansale/install.py` with `ensure_capacitor_cors()` — copy verbatim from `frappe-vue-pwa` §3.6 (origins: `https://localhost`, `capacitor://localhost`, `http://localhost`).
- [ ] **Step 5: Commit** `feat(backend): scaffold vansale Frappe app with CORS installer`.

### Task 3 — `Vansale Pin` DocType + secrets util

- [ ] **Step 1:** Write `vansale/doctype/vansale_pin/vansale_pin.json` — single doctype, fields `user (Link → User, unique)`, `pin_hash (Password)`, `created_at (Datetime)`. Permissions: System Manager full + Employee read/write on own.
- [ ] **Step 2:** Write stub `vansale_pin.py` controller.
- [ ] **Step 3:** Write `vansale/utils/secrets.py` with `get_or_create_stable_secret(user_doc)` — generates `api_key`/`api_secret` on first call, **reuses existing** on subsequent (see `frappe-vue-pwa` §3.5 rule 7).
- [ ] **Step 4: Commit** `feat(backend): Vansale Pin doctype + stable api_secret helper`.

### Task 4 — Auth API

- [ ] **Step 1:** Write `vansale/api/auth.py` with:
  - `login(usr, pwd)` (cookie-based, calls `frappe.auth.LoginManager`, returns `{user, full_name}`)
  - `setup_pin(pin)` (logged-in, stores bcrypt hash in `Vansale Pin`)
  - `login_with_pin(email, pin)` — bcrypt.checkpw using `doc.get_password("pin_hash")`, then `get_or_create_stable_secret()` (see `frappe-vue-pwa` §3.5)
  - `change_pin(old, new)`
  - `ping()` — returns `{user, timestamp}`
- [ ] **Step 2:** Write `vansale/api/util.py` — `get_csrf_token()` (whitelisted guest), `version_compat()` returning `{min, current}`.
- [ ] **Step 3:** Write `vansale/api/__init__.py` (empty).
- [ ] **Step 4: Commit** `feat(backend): auth endpoints (login, setup_pin, login_with_pin, change_pin)`.

### Task 5 — Fixtures + custom fields (empty scaffolding)

- [ ] **Step 1:** Write `vansale/fixtures/custom_field.json` = `[]` for now (P3 fills it).
- [ ] **Step 2: Commit** `chore(backend): empty custom_field fixture`.

### Task 6 — Vue 3 frontend scaffold

- [ ] **Step 1:** `cd frontend && pnpm init` (name `vansale-frontend`, type module).
- [ ] **Step 2:** `pnpm add vue@^3.4 vue-router@^4.3 pinia@^2.1 vue-i18n@^9 idb@^8`.
- [ ] **Step 3:** `pnpm add -D @vitejs/plugin-vue@^5 vite@^5 typescript vue-tsc @types/node`.
- [ ] **Step 4:** Write `package.json` scripts: `dev`, `build`, `preview`, `type-check` = `vue-tsc --noEmit`.
- [ ] **Step 5:** Write `tsconfig.json` (strict, target ES2020, vue shim).
- [ ] **Step 6:** Write `vite.config.ts` per `frappe-vue-pwa` §3.2 — `base` = `"/assets/vansale/spa/"` on build when `CUSTOMER_BUILD_TARGET=web`, `"./"` when `native`; outDir = `../vansale/public/spa`. Proxy `/api` → `http://127.0.0.1:8000` in dev.
- [ ] **Step 7:** Write `index.html` loading `/src/main.ts`.
- [ ] **Step 8:** Write `.env.example` with `CUSTOMER_NAME`, `CUSTOMER_APP_ID`, `CUSTOMER_THEME_PRIMARY`, `VITE_API_BASE`, `VITE_APP_TITLE`.
- [ ] **Step 9:** Write `.gitignore` (node_modules, dist, .env.*).
- [ ] **Step 10: Commit** `feat(frontend): Vite + Vue 3 scaffold`.

### Task 7 — Platform + frappe facade

- [ ] **Step 1:** Write `src/app/platform.ts` — `isNative()` + `API_BASE()` per `frappe-vue-pwa` §3.3.
- [ ] **Step 2:** Write `src/app/frappe.ts` — `apiCall(method, path, body?)`, `getCredentials/setCredentials` (Preferences stub for web; full plugin wired in P5), `loginWithPin`, `ApiError` class (distinct from network errors — §4.2 commandment 2), `saveBlobToDevice()` stub for PDF downloads (P4). **GET params in URL** (lesson 13). All datetimes must be `new Date(utcIso).toLocaleString()` — never string-slice.
- [ ] **Step 3:** Write `src/api/client.ts` — thin wrapper exporting `apiCall`.
- [ ] **Step 4:** Write `src/api/auth.ts` — `login`, `setupPin`, `loginWithPin`, `changePin`, `ping` wrappers.
- [ ] **Step 5:** Write `src/stores/session.ts` (Pinia) — holds `user`, `fullName`, `credentials`, `pinVerifiedAt`. Persists to localStorage.
- [ ] **Step 6: Commit** `feat(frontend): platform + frappe facade + session store`.

### Task 8 — Router + views

- [ ] **Step 1:** Write `src/app/router.ts` — `createWebHashHistory()` if `isNative()`, else `createWebHistory("/vansale/")` (§3.7). Routes: `/login`, `/pin`, `/`, `/dashboard`. `beforeEach` guard redirects to `/login` if no session, `/pin` if session but no pinVerifiedAt < 2h.
- [ ] **Step 2:** Write `src/app/i18n.ts` — vue-i18n setup, en + ar locales stub.
- [ ] **Step 3:** Write `src/views/LoginView.vue` — email + password; on success → `/pin` for setup.
- [ ] **Step 4:** Write `src/views/PinView.vue` — 4–6 digit PIN; two modes (setup vs unlock); offline unlock via local hash (lesson §5.3: try local hash first, fall back to server).
- [ ] **Step 5:** Write `src/views/DashboardView.vue` — stub: "Hello {{ fullName }}" + env + NATIVE_VERSION.
- [ ] **Step 6:** Write `src/components/TopAppBar.vue`.
- [ ] **Step 7:** Write `src/styles/tokens.css` (neutral CSS vars — primary, bg, surface, text, radius, spacing) + `src/styles/base.css` (reset).
- [ ] **Step 8:** Write `src/main.ts` — create app, mount, register Pinia/router/i18n; register SW `/sw.js` only when `!isNative()`.
- [ ] **Step 9:** Write `src/app/App.vue` — `<RouterView/>` + top bar.
- [ ] **Step 10: Commit** `feat(frontend): router + auth views + session guard`.

### Task 9 — Theming plugin

- [ ] **Step 1:** Write `frontend/plugins/vite-theme-plugin.ts` — reads `CUSTOMER_*` env at build, emits `<style>:root{ --primary: ...; }</style>` into index.html. (Fateh HR pattern — keep minimal in P1.)
- [ ] **Step 2:** Write `frontend/plugins/theme-utils.ts`.
- [ ] **Step 3:** Commit `feat(frontend): Vite theme plugin for white-label CSS vars`.

### Task 10 — Deploy pipeline skeleton

- [ ] **Step 1:** Write `scripts/build-customer.sh` — P1 stub: reads `customers/.env.$1`, runs `pnpm build`, prints next-step reminder (full APK pipeline wired in P5).
- [ ] **Step 2:** Write `scripts/bump-version.mjs` — stub that writes `frontend/src/app/native-version.ts` with `NATIVE_VERSION` + `NATIVE_VERSION_CODE` (both = 1 at P1).
- [ ] **Step 3:** Write `customers/.env.example` with demo placeholders.
- [ ] **Step 4: Commit** `chore(deploy): stub build pipeline scripts`.

### Task 11 — Handoff docs

- [ ] **Step 1:** Write `docs/AGENT_HANDOFF.md` — mirror Fateh HR's (infra TBD, demo tenant TBD, deploy pipeline placeholder, "read frappe-vue-pwa skill first").
- [ ] **Step 2:** Write `docs/LESSONS_LEARNED.md` — single line: "Source of truth = frappe-vue-pwa skill. This file grows per phase."
- [ ] **Step 3: Commit** `docs: initial agent handoff + lessons placeholder`.

### Task 12 — Server deploy (deferred)

Server install (`bench get-app`, `bench install-app`, site creation) happens when user nominates a target server + demo tenant name. Not in this plan's execution — scaffold locally, commit, hand off.

- [ ] **Step 1:** Note deferred work in `docs/AGENT_HANDOFF.md` under "Open Items" with exact commands to run (from `enfono-servers` skill).

---

## Exit criteria for Phase 1

- `pnpm --filter frontend type-check` passes.
- `pnpm --filter frontend build` produces `vansale/public/spa/index.html`.
- `vansale/api/auth.py` endpoints importable (no syntax errors).
- Git log: 10+ clean commits, each focused.
- `docs/AGENT_HANDOFF.md` has the exact bench commands to install on a server.

## What's deferred to later phases

- P2: IndexedDB, offline queue, drain engine, photo/signature uploader.
- P3: Domain endpoints (customers, items, invoice, payment, returns, dashboards).
- P4: Van stock ledger, route planning, barcode, signature, receipt print, GPS.
- P5: Capacitor shell, APK signing, Filesystem downloads, back-button hierarchy.
