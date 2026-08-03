# Per-customer artwork

One folder per customer, matching `CUSTOMER_NAME` in `customers/.env.<customer>`:

```
customers/assets/<customer>/
  icon.png     1024×1024 PNG, no transparency at the edges — launcher icon + splash source
  splash.png   2732×2732 PNG, optional — falls back to icon.png on a solid CUSTOMER_THEME_BG
  logo.png     in-app brand mark on the login / PIN screens, optional — falls back to icon.png
```

`scripts/build-customer.sh` consumes these in two stages:

- **before** the Vite builds, `generate-customer-assets.mjs brand` copies `logo.png`
  into `frontend/public/` and `android-capacitor/public/` as `brand-logo.png`
- **after** `npx cap copy android`, `generate-customer-assets.mjs android` runs
  `@capacitor/assets` to regenerate every `mipmap-*` / `drawable-*` density from
  `icon.png`

Missing files are warnings, never build failures — the APK still assembles with
the Capacitor default icon and the built-in truck mark. First run needs network
so `npx` can fetch `@capacitor/assets`.

Icon requirements that actually bite:

- **Square, 1024×1024.** Non-square input gets letterboxed.
- **Keep the logo inside the centre ~66%.** Android adaptive icons crop to a
  circle/squircle on most launchers; artwork near the edge gets clipped.
- **No text smaller than ~80px** at 1024 — it disappears at mdpi.
