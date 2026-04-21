# Van Sales — Demo Site

Static landing page for the Van Sales demo. Pure HTML/CSS/JS — no build step.

## Deploy to Vercel

```bash
cd docs-site
vercel deploy --prod
```

Or via the dashboard: import this folder as a new Vercel project and set the
root directory to `docs-site/`. No framework preset needed — Vercel serves the
static files directly.

## Files

| File           | Purpose                                            |
| -------------- | -------------------------------------------------- |
| `index.html`   | Landing page markup                                |
| `styles.css`   | All styling (no framework, no build)               |
| `app.js`       | Copy-to-clipboard + scroll-reveal                  |
| `vercel.json`  | Caching + security headers                         |

## Content

The page has six sections:

1. **Hero** — product pitch + two CTAs (Download APK, See credentials).
2. **Demo credentials** — `vanuser@gmail.com` / `Van@123456` with copy buttons.
3. **Features** — six-tile grid of what the app does.
4. **Install** — three-step guide for sideloading the APK.
5. **Tour** — one-minute walkthrough of the in-app flow.
6. **FAQ** — common questions.

## Updating the APK link

The hero CTA and step-1 install link both point at
`https://github.com/EnfonoTech/vansale/releases/latest`. That redirects to the
newest tagged release — no edit needed when bumping versions. If the repo URL
changes, update both anchors and the `#app-version` badge in `index.html`.
