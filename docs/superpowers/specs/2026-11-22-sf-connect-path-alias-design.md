# /sf-connect as a second address for the web app

Date: 2026-11-22. Branch `develop_2`. Approved in chat: serve both addresses.

**Intent.** Steel Force wants to share `/sf-connect` instead of `/vansale`. `/vansale` must keep working, so installed home-screen apps, bookmarks and push notifications do not break.

**Design.** The same page and built files are served at both addresses. `website_route_rules` send `/sf-connect` and `/sf-connect/<path>` to `www/vansale`. `vansale.pwa.scope_of(path)` tells which address a request belongs to; the manifest, service worker (with its `Service-Worker-Allowed` scope), icons and the page's head tags are built for that address, so an install made at `/sf-connect` is scoped to it. In the SPA, `web-base.ts` derives the router base and the worker scope from the path the app was opened at. Built assets stay under `/assets/vansale/spa/` (that is the app's folder).

**Calls made (not asked).** The alias is a fixed `/sf-connect`, not a setting: Frappe route rules are hook constants and cannot read a database value. `role_home_page`, the desk boot route and the site-root redirect stay `/vansale`, because the code is shared with other customers (Badria) who would not want a Steel Force path as their default. Push payload URLs are still `/vansale/approvals`; the `/sf-connect` worker accepts only URLs under its own scope and otherwise opens its own inbox.

**Not covered.** The Android app (hash routing, no server path). Renaming `/assets/vansale/spa/`.
