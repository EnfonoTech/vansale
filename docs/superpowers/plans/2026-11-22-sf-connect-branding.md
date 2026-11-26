# SF Connect branding and login styles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The van app's name, logo and sign-in style come from Vansale Settings at runtime, so the desk can change them without a rebuild.

**Architecture:** Three new fields on Vansale Settings (one reused). A public `branding` endpoint returns them. The SPA keeps a small cached store, and the sign-in and PIN screens read it. A global stylesheet draws the three styles from a class on the existing wrapper.

**Tech Stack:** Frappe v15 (Python, site-free `unittest`), Vue 3 + TypeScript + Vite, Vitest (happy-dom), pnpm.

**Spec:** `docs/superpowers/specs/2026-11-22-sf-connect-branding-design.md`

## Global Constraints

- Branch `develop_2` of `EnfonoTech/vansale`; commit as `sivajyothis7` with no co-author trailer; push to GitHub; do not deploy.
- Reuse `pwa_app_name` ("App name") and `pwa_icon` ("App icon"); add `login_logo` (Attach Image, "Login logo") and `login_style` (Select, options `Classic`, `Split`, `Dark glass`, default `Classic`).
- Section `section_break_install` label becomes "Branding and install on phone".
- Endpoint: `vansale.api.auth.branding`, `allow_guest=True`, `methods=["GET"]`, returns `{app_name, logo_url, style}`; `style` is one of `classic`, `split`, `dark`.
- A `/private/` file URL is never returned.
- Fallbacks in the SPA: build title `__APP_TITLE__`, built-in truck mark, `classic`. Other customers keep "Van Sale" because the fields are blank by default.
- Not in scope: Android launcher label/icon, per-driver style choice, a theme-colour field. Accent follows the app's `--primary`.
- Python tests are site-free (`vansale/tests/_site_free.py`); the frontend uses `pnpm`, never npm.

## Review Focus

- First ever open with no cache and the request failing: sign-in renders with the build title, the truck and Classic (Task 2).
- A garbage or old-format cache entry: ignored, not thrown (Task 2).
- An app name that is long or contains markup: capped at 40 characters and shown as text (Task 2).
- A logo URL that 404s: the truck shows, never a broken-image glyph (Task 3's `@error` fallback; looked at in the browser after the later sft-uat deploy, which is outside this plan).
- Native build before a server is set: `apiBase()` throws and the refresh must swallow it (Task 2).
- Style blank or no longer a known option in settings: `classic` (Tasks 1 and 2).

## File Structure

- Modify `vansale/vansale/doctype/vansale_settings/vansale_settings.json`: fields and `field_order`.
- Create `vansale/branding.py`: `get_branding()`.
- Modify `vansale/api/auth.py`: the `branding` endpoint next to `site_info`.
- Create `vansale/tests/test_branding.py`.
- Create `frontend/src/app/branding.ts` and `frontend/src/app/__tests__/branding.test.ts`.
- Modify `frontend/vitest.config.ts`: define `__APP_TITLE__`.
- Create `frontend/src/styles/auth-styles.css` and import it where the other global styles load (see `frontend/src/main.ts`).
- Modify `frontend/src/components/BrandMark.vue`, `views/LoginView.vue`, `views/PinView.vue`, `views/SiteSetupView.vue`, `components/TopAppBar.vue`.

### Task 1: Settings fields and the branding endpoint

**Files:**
- Modify: `vansale/vansale/doctype/vansale_settings/vansale_settings.json`, `vansale/api/auth.py`
- Create: `vansale/branding.py`, `vansale/tests/test_branding.py`

**Interfaces:**
- Produces: `vansale.branding.get_branding() -> dict[str, str]` with keys `app_name`, `logo_url`, `style`; `vansale.api.auth.branding() -> dict[str, str]` (same dict).

- [ ] **Step 1: Write the failing tests** in `vansale/tests/test_branding.py`, patching `vansale.pwa._settings` (returns the singles dict):
  - `test_empty_settings` → `get_branding() == {"app_name": "", "logo_url": "", "style": "classic"}`
  - `test_name_is_stripped` → `"  SF Connect "` gives `"SF Connect"`
  - `test_login_logo_beats_app_icon` and `test_app_icon_is_the_fallback`
  - `test_private_url_is_dropped` → `login_logo="/private/files/a.png"`, `pwa_icon="/files/b.png"` gives `"/files/b.png"`; both private gives `""`
  - `test_style_map` → `"Classic"`, `"Split"`, `"Dark glass"` give `classic`, `split`, `dark`; `""`, `None`, `"Neon"` give `classic`
  - `test_endpoint_is_guest_and_get_only` → `auth.branding in frappe.guest_methods`; `auth.branding()` equals `get_branding()`

- [ ] **Step 2: Run to verify they fail.** On sft-uat, copy the clone to `/tmp/vansale_t/` (own directory, readable) and run `cd /home/frappe/frappe-bench/sites && PYTHONPATH=/tmp/vansale_t /home/frappe/frappe-bench/env/bin/python -m unittest vansale.tests.test_branding -v`. Expected: `ModuleNotFoundError: vansale.branding`.

- [ ] **Step 3: Implement `get_branding() -> dict` in `vansale/branding.py`** reading `vansale.pwa._settings()`. `logo_url` is the first of `login_logo`, `pwa_icon` that is non-empty and does not start with `/private/`. Style map as in Global Constraints, default `classic`.

- [ ] **Step 4: Add `@frappe.whitelist(allow_guest=True, methods=["GET"]) def branding()` to `vansale/api/auth.py`** returning `get_branding()`, with a docstring that justifies `allow_guest` (the values are what the public sign-in page already shows, no tenant or user data).

- [ ] **Step 5: Add the fields to the DocType JSON**: `login_logo` after `pwa_icon` and `login_style` after it in both `fields` and `field_order`; retitle the section.

- [ ] **Step 6: Re-run the tests.** Expected: all pass. Also run `python -c "import json; json.load(open(...))"` on the JSON.

- [ ] **Step 7: Commit** `feat(branding): Vansale Settings name, logo and login style, public branding endpoint`.

### Task 2: The SPA branding store

**Files:**
- Create: `frontend/src/app/branding.ts`, `frontend/src/app/__tests__/branding.test.ts`
- Modify: `frontend/vitest.config.ts` (add `__APP_TITLE__: JSON.stringify("Van Sale")` to `define`)

**Interfaces:**
- Produces, all exported from `@/app/branding`:
  - `type LoginStyle = "classic" | "split" | "dark"`
  - `interface Branding { appName: string; logoUrl: string; style: LoginStyle }`
  - `const BRANDING_CACHE_KEY = "vansale.branding"`
  - `normalizeBranding(raw: unknown): Branding`: accepts the endpoint's `{app_name, logo_url, style}` or the cached `Branding`; anything else gives the fallbacks; `appName` trimmed and cut to 40 characters; unknown style gives `classic`
  - `authStyleClass(style: LoginStyle): string` returns `auth-style-<style>`
  - `useBranding(): { branding: Readonly<Ref<Branding>>; refreshBranding(): Promise<void> }`: a module-level singleton, initial value from `localStorage` else fallbacks
  - `resetBrandingForTests(): void`

- [ ] **Step 1: Write the failing tests** (`vi.stubGlobal("fetch", ...)`, `window.localStorage.clear()` in `beforeEach`, `vi.mock("@/app/platform")` for `apiBase`):
  - `falls back to the build title, no logo and Classic when nothing is set`
  - `reads the value an earlier fetch cached`
  - `ignores a garbage cache entry` (`localStorage.setItem(KEY, "{nope")`)
  - `an unknown style becomes classic`
  - `a long or markup name is cut to 40 characters and kept as plain text`
  - `refreshBranding stores the answer and updates the reactive value` (response body `{message: {app_name: "SF Connect", logo_url: "/files/e.png", style: "split"}}`)
  - `refreshBranding keeps the cached value when the request fails` (fetch rejects, and a non-OK response)
  - `refreshBranding does nothing when no server is configured` (`apiBase` throws; `fetch` not called)
  - `authStyleClass("dark") === "auth-style-dark"`

- [ ] **Step 2: Run** `cd frontend && npx pnpm@9 install --frozen-lockfile && npx pnpm@9 test -- branding`. Expected: FAIL, module not found.

- [ ] **Step 3: Implement `frontend/src/app/branding.ts`.** `refreshBranding` fetches `${apiBase()}/api/method/vansale.api.auth.branding` (GET, no credentials needed, short timeout), reads `message`, passes it through `normalizeBranding`, runs `logoUrl` through `absoluteUrl` from `@/app/platform`, writes the cache and updates the ref. Every `localStorage` access sits in try/catch. Errors are swallowed.

- [ ] **Step 4: Re-run the tests.** Expected: pass. Also `npx pnpm@9 type-check`.

- [ ] **Step 5: Commit** `feat(branding): SPA branding store with cached values`.

### Task 3: Brand mark, three styles, and the screens

**Files:**
- Create: `frontend/src/styles/auth-styles.css`
- Modify: `frontend/src/components/BrandMark.vue`, `frontend/src/views/LoginView.vue`, `PinView.vue`, `SiteSetupView.vue`, `frontend/src/components/TopAppBar.vue`, `frontend/src/main.ts` (import the stylesheet)

**Interfaces:**
- Consumes: `useBranding`, `authStyleClass` from Task 2.

- [ ] **Step 1: `BrandMark.vue` takes its image from `branding.logoUrl`** and falls back, in order, to the build-time `brand-logo.png`, then the truck `Icon` (the existing `@error` swap stays; reset the fallback flag when `logoUrl` changes).

- [ ] **Step 2: `LoginView.vue`, `PinView.vue`, `SiteSetupView.vue`:** replace `__APP_TITLE__` with `branding.appName`; add `:class="authStyleClass(branding.style)"` to the `.auth-wrap` element; call `refreshBranding()` in `onMounted` (SiteSetupView calls it only after a site is connected; before that it shows the cached/fallback values). PinView's heading keeps its own text.

- [ ] **Step 3: `TopAppBar.vue`:** the last-resort title `"Van Sale"` (line 130) becomes `branding.appName`.

- [ ] **Step 4: Write `frontend/src/styles/auth-styles.css`** with rules scoped as `.auth-wrap.auth-style-split …` and `.auth-wrap.auth-style-dark …`; Classic has no rules (today's look). The values come from the approved mockup:
  - **Split:** `.brand` becomes a full-width block with `background: var(--primary)`, `color: var(--primary-ink)`, the logo tile white, about 9.5rem tall; the form below sits flat (no card shadow or border); at `min-width: 768px` and `min-height: 600px` the brand block moves to a left column and the form to the right.
  - **Dark glass:** wrapper `background: #0b1220`; `.brand h1` `#fff`; `.muted` `#94a3b8`; `.card` and `.pin-card` `background: rgba(255,255,255,0.07)`, `border: 1px solid rgba(255,255,255,0.18)`, no shadow; inputs `background: rgba(255,255,255,0.06)`, `border-color: rgba(255,255,255,0.2)`, `color: #fff`; `.brand-mark` `#fff`; PIN dots stay visible on dark.
  - Both styles must keep the safe-area padding and the existing tablet sizes working.

- [ ] **Step 5: Verify:** `npx pnpm@9 type-check`, `npx pnpm@9 test`, `npx pnpm@9 build` (output is gitignored). Expected: all green.

- [ ] **Step 6: Commit** `feat(branding): login and PIN screens use the branding store, three login styles`.

### Task 4: Hand-off artefacts and push

**Files:**
- Create: `C:\Users\sivaj\Documents\Enfono General\sf-connect-emblem.png` (the emblem cut from page 1 of `Steel Force Logo.pdf`, 512 px wide, for uploading as the Login logo and App icon).

- [ ] **Step 1: Export the emblem** with PyMuPDF (installed in the scratchpad `pylib`), clip `Rect(690, 355, 1185, 928)` of the 150 dpi page scaled by 72/150, rendered at 300 dpi.

- [ ] **Step 2: Run the whole suite once more** (`pnpm test`, `pnpm type-check`, the Python test on sft-uat) and confirm the working tree only holds the intended files.

- [ ] **Step 3: Pull, then push** `develop_2`: `git pull --ff-only origin develop_2` then `git push origin develop_2`. Do not touch any server.
