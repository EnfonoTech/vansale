# SF Connect: app name, logo and login style from Vansale Settings

Date: 2026-11-22. Branch: `develop_2` (the Steel Force build). Status: awaiting approval.

## Intent

Steel Force wants the van app to read "SF Connect" with the Steel Force logo, and the admin must be able to change
the name, the logo and the look of the sign-in screen from the desk later, without a rebuild or a tarball.

## Goals

- App name, logo and login style are fields on Vansale Settings and take effect without rebuilding the SPA.
- The sign-in, PIN and site-setup screens show them. The top bar's fallback title shows the app name.
- The sign-in screen still renders correctly offline and before the first fetch, from the last values seen.
- Other customers (Badria) keep "Van Sale" and the truck mark unless they set values.

## Non-goals

- The Android launcher label and APK icon (baked at build time; renaming them needs a rebuild of the APK).
- Each driver choosing a style. The admin chooses one for everybody.
- Per-van branding, or changing colours in the rest of the app.

## Anti-goals

- A flash of "Van Sale" before "SF Connect" appears.
- A sign-in screen that breaks, or shows a broken image, when the branding request fails or the phone is offline.
- Leaking anything but what the public sign-in page already shows.

## Approaches

- **A. Runtime settings + a small public endpoint + a local cache (chosen).** Name, logo and style live on Vansale
  Settings; the SPA asks a guest endpoint and remembers the answer.
- B. Build-time per-customer variables (how it works today: `__APP_TITLE__`, `brand-logo.png`). Rejected: every change
  needs a rebuild and a tarball, so the desk cannot change it.
- C. Put the values into the server-rendered `/vansale` page. Rejected: the Android app serves bundled files, not that
  page, and a kept offline copy of the page would hold stale values.

## Design

**Settings** (Vansale Settings, Single). Reuse `pwa_app_name` ("App name", already drives the install name) and
`pwa_icon` ("App icon", the install icon). Add `login_logo` (Attach Image, "Login logo"; blank falls back to App icon,
then to the built-in truck) and `login_style` (Select: Classic, Split, Dark glass; default Classic). Section retitled
"Branding and install on phone".

**Endpoint.** `vansale.api.auth.branding`, `allow_guest=True`, GET. Returns `{app_name, logo_url, style}`; empty
strings when unset; an unknown style becomes `classic`. `logo_url` is returned only for a public file (a
`/private/` URL cannot be fetched before sign-in, so it is dropped).

**SPA.** `frontend/src/app/branding.ts`: a small reactive store. It starts from `localStorage` (`vansale.branding`,
read and written inside try/catch), fetches the endpoint when the sign-in, PIN or site-setup screen opens and at app
start, updates itself and the cache. Fallbacks: `__APP_TITLE__`, the truck, Classic. `LoginView` and `PinView` read
the store; the root element carries `auth-style-<style>` and three scoped CSS blocks draw them: Classic is today's
centred card, Split puts a brand panel (logo, name) beside the form, Dark glass is a dark background with a frosted
card. `BrandMark` takes the logo URL from the store. `TopAppBar`'s fallback title uses the app name.

**Data, not code.** After deploy, "SF Connect" and the Steel Force emblem are entered in Vansale Settings on the
Steel Force site (UAT first). The emblem is cut from the logo PDF supplied (page 1).

## Tests

- Python: endpoint is reachable as guest; empty settings give empty strings; invalid style gives `classic`; a
  private file URL is not returned.
- Vitest: branding store reads the cache, falls back, and writes after a fetch.
- Browser check on sft-uat: all three styles, light and dark, phone width, offline reload.

## Delivery

Commit and push to `develop_2` (repo first). Deploying to sft-uat means `pnpm build` and the tarball steps in
`docs/OPERATIONS.md`; production only when asked.

## Left to the builder

Exact colours and spacing of Split and Dark glass; logo sizing and fit inside each style; how the Capacitor build
reaches the endpoint (it already knows the site URL from setup).
