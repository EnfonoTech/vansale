# Van Sale — Agent Handoff

> **Start here if you're a fresh agent picking up this repo.**
> This file grows with the project. As of 2026-04-19 it covers Phase 1
> (Foundation). Phase plans are in [`superpowers/plans/`](superpowers/plans/).

---

## 1. What this project is

Offline-first van-sales PWA on Frappe v15 + ERPNext. One Vue 3 source
tree ships as both a web PWA (at `/vansale`) and a signed Capacitor
Android APK (added in Phase 5). Replaces the existing `fateh_pwa` React
PWA — same domain, new spine that inherits every lesson from the Fateh
HR rebuild.

**Architecture source of truth:** `~/.claude/skills/frappe-vue-pwa/SKILL.md`.
**Infra + deploy source of truth:** `~/.claude/skills/enfono-servers/SKILL.md`.
**Deploy pipeline reference:** `~/.claude/skills/fatehhr/SKILL.md`
(mirror the commands, swap paths / app id / keystore).

---

## 2. Current state (Phase 1 complete locally)

| Thing | Value |
|---|---|
| Repo root | `/Users/sayanthns/ERP - PWAs/vansale/` |
| Frappe app | `vansale` (module `Vansale`) |
| SPA path | `/vansale` → `/assets/vansale/spa/index.html` |
| Web route | `/vansale` (via `website_redirects`) |
| Native APK id | `com.enfono.vansale.<customer>` (template; Phase 5 picks first customer) |
| Python app version | `0.0.1` |
| Frontend `NATIVE_VERSION` | `1.0.0` / code 1 |
| Server + demo tenant | **TBD** — user has not yet nominated a target |

### What Phase 1 delivered

- Frappe app scaffold: `hooks.py` (CORS `after_migrate`, website redirects, fixtures), `install.py::ensure_capacitor_cors`, `Vansale Pin` DocType, `utils/secrets.py` with stable `api_secret` issuance.
- Auth endpoints: `login`, `setup_pin`, `login_with_pin`, `change_pin`, `ping`, `logout` — all with the rule-8 `doc.get_password()` read and rule-7 stable token reuse.
- Vue 3 SPA skeleton: platform detection (`isNative`, `apiBase`, `absoluteUrl`), `frappe.ts` API facade with `ApiError` vs `NetworkError` separation, Pinia session store with localStorage persistence + 2h PIN window, router with hash-on-native / history-on-web, Login + PIN (setup/unlock) + stub Dashboard, English + Arabic locales with RTL, white-label theme plugin.
- Deploy-pipeline stubs: `scripts/bump-version.mjs`, `scripts/build-customer.sh`, `customers/.env.example`.

### Deferred to Phase 5

- Server install + demo tenant (needs user decision: which server, which site name).
- APK build pipeline + keystore.
- Full `saveBlobToDevice` (currently web-only).

---

## 3. Install on a target server (when nominated)

Use the Enfono Server Manager API. Defaults assume AQRAR + `vansale_demo`,
but pick whatever the user requests.

```bash
# Run via server-manager /api/servers/<ID>/command — see enfono-servers skill.

set -e
cd /home/v15/frappe-bench
sudo -u v15 bench get-app <this_repo> --branch develop

# Per enfono-servers rule #5 — pip install -e after every app install,
# otherwise Gunicorn throws ModuleNotFoundError on every request.
/home/v15/frappe-bench/env/bin/pip install -e /home/v15/frappe-bench/apps/vansale

# Create site (maintenance window only).
sudo -u v15 bench new-site vansale_demo \
  --mariadb-root-password "<ROOT>" \
  --admin-password "<ADMIN>" \
  --mariadb-user-host-login-scope="%"
sudo -u v15 bench --site vansale_demo install-app erpnext
sudo -u v15 bench --site vansale_demo install-app vansale

# wkhtmltopdf needs host_name for PDF rendering (fatehhr lesson #6):
sudo -u v15 bench --site vansale_demo set-config host_name https://<domain>

# Reload workers without full restart (business-hours hot reload).
sudo supervisorctl signal QUIT frappe-bench-web:frappe-bench-frappe-web
sudo supervisorctl signal QUIT frappe-bench-workers:frappe-bench-frappe-long-worker-0
sudo supervisorctl signal QUIT frappe-bench-workers:frappe-bench-frappe-short-worker-0
```

Caddy SSL vs certbot — check `sslMode` per `enfono-servers` inventory
before provisioning a domain.

---

## 4. Local dev loop

```bash
cd frontend
pnpm install
pnpm dev          # Vite on :8082 with /api proxy to a local bench
pnpm type-check   # vue-tsc --noEmit
pnpm build        # → ../vansale/public/spa/
```

Set `VITE_API_BASE` in `frontend/.env.local` for native builds; web
build uses same-origin and needs nothing.

---

## 5. Testing hooks

- **Auth smoke:** `curl -X POST .../api/method/vansale.api.auth.login -d '{"usr":"...","pwd":"..."}'`
- **PIN smoke:** after `login`, `curl -X POST .../api/method/vansale.api.auth.setup_pin -d '{"pin":"1234"}'`
- **Token smoke:** hit `/api/method/vansale.api.auth.ping` with `Authorization: token <key>:<secret>`.
- **CORS smoke on a Capacitor origin:** `-H "Origin: https://localhost"` → should not 403.

---

## 6. Open items (end of Phase 1)

- [ ] User nominates target server + demo site name (`vansale_demo` suggested).
- [ ] User confirms GitHub remote (new `EnfonoTech/vansale` repo? reuse existing?). No push has been done.
- [ ] Phase 2 execution — offline engine (see [`superpowers/plans/2026-04-19-vansale-phase2-offline-engine.md`](superpowers/plans/2026-04-19-vansale-phase2-offline-engine.md)).

---

## 7. Pair skills

- **`frappe-vue-pwa`** — architecture source of truth.
- **`enfono-servers`** — server inventory, SSH/API, safety rules, maintenance window.
- **`fatehhr`** — mirror deploy pipeline (swap paths + app id).

Read all three before any substantive change to this repo.
