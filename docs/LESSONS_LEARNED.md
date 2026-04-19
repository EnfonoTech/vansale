# Lessons Learned

Running diary of what broke during the Van Sale rebuild, why, and the fix.
The **source of truth** for architectural rules is `~/.claude/skills/frappe-vue-pwa/SKILL.md` — that skill codifies every lesson the Fateh HR rebuild taught us. This file only records Van-Sale-specific findings on top of that baseline.

---

## Pre-rebuild audit (2026-04-19)

Studied both `EnfonoTech/Van-Sales` (first-gen backend, 477-line `api.py`) and `EnfonoTech/Van-Sales-PWA` (a.k.a. `fateh_pwa`, React 19 + Vite 7 + react-router 7). Key findings that shape Phase 1–5:

1. **`fateh_pwa` pretends to be offline-first but isn't.** The "queued" counter reads `localStorage["pwa-queued-requests"]` but nothing ever writes it. `apiRequest` throws the string `"OFFLINE"`; `SalesModule` stashes `_queued:true` on an in-memory object and shows an alert. No IndexedDB, no drain, no dedup, no photo uploader. → Phase 2 installs the real spine from `frappe-vue-pwa` §4.
2. **No Capacitor / APK.** Service-worker-only browser PWA. → Phase 5 adds the shell exactly like Fateh HR's.
3. **Auth stores `api_key` / `api_secret` in plain `localStorage`**, no PIN, no biometric. → Phase 1 replaced with the stable-secret PIN flow. `Vansale Pin` bcrypt-hashed; secret reused on every unlock (`frappe-vue-pwa` §3.5 rule 7).
4. **Datetimes returned naive from `fateh_pwa`**, same bug that bit Fateh HR's round-two (fatehhr lesson #9). → Phase 2 adds `parse_client_ts` + `naive_site_to_utc_iso` up front.
5. **PDF download via `<a download>`** — silently no-op in Android WebView. → `saveBlobToDevice` stubbed in Phase 1; full wiring with `@capacitor/filesystem` in Phase 5 (same pattern as fatehhr lesson #10.1).
6. **No signature, barcode, GPS, van-stock, receipt printing.** → New Phase 4 features, each offline-capable via the Phase 2 spine.

---

## Phase 1 — Foundation (2026-04-19)

- **Password fields mask on attribute access.** `doc.pin_hash` returns 60 asterisks; `doc.get_password("pin_hash")` returns the real bcrypt hash. Forgetting this sends `bcrypt.checkpw` into `Invalid salt`. Codified in `vansale/api/auth.py` (explicit comment on the `login_with_pin` path). Same rule applies anywhere a `Password` fieldtype is read.
- **Static imports for all `@capacitor/*`.** Declared in `frontend/package.json` so the web build resolves them; web runtime is inert because every caller guards with `isNative()`. Dynamic imports hang silently inside the Android WebView (`frappe-vue-pwa` §3.4 rule 14).
- **`ApiError` vs `NetworkError`** set up up front in `src/app/frappe.ts`. The queue-drain logic in Phase 2 will `instanceof ApiError`-check and re-throw; only network failures get queued. Skipping this step on Fateh HR cost two point-releases (fatehhr lesson #2).
- **Router history mode is decided at module load** via `isNative()` because route objects freeze once Vue boots — changing history later requires a full re-init. Hash on native, path on web (`createWebHistory("/vansale/")`).

---

## Standing rules (inherited)

Full list lives in `~/.claude/skills/frappe-vue-pwa/SKILL.md` §5 (20 commandments) — read it. The highlights every Van Sale commit must honour:

1. Datetimes to client → **UTC-ISO with `Z`**. Never naive.
2. Any new Capacitor plugin → `pnpm add` in **BOTH** `frontend` AND `android-capacitor`, then `npx cap sync android`.
3. GET body is silently dropped — params belong in the URL.
4. `ApiError` ≠ network error. Re-throw; queue only on network failures.
5. ONE uploader per photo/signature blob. No fire-and-forget pre-upload.
6. Never silently delete user work. Tag orphans, let the user decide.
7. `bump-version.mjs` is the only way to bump `NATIVE_VERSION` + `versionCode`.
8. Maintenance window for bench restarts = **2:00–5:00 AM IST**. Business-hours hot reload via `supervisorctl signal QUIT`.
9. Never commit `dist/`, `*.apk`, `*.keystore`, `.vue.js` artefacts.
10. Check Frappe Error Log **before** shipping any speculative fix.
