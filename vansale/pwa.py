"""Install support for the web app ("Add to Home screen").

Served under /vansale, so the installed app and its service worker cover only
the van-sales screens. Frappe sites may already serve another app's worker
at /sw.js (POS Awesome on Badria); registering that one made the phone see
POS Awesome's manifest, and Van Sale had none, so it could not be installed.

  /vansale/manifest.webmanifest  name, icons, start URL, standalone display
  /vansale/sw.js                 service worker (offline start, shows approval pushes, see SW_JS)
  /vansale/shell-files.json      the built app's files, for the worker to keep (offline start)
  /vansale/icon-<size>.png       Vansale Settings "App icon", else the default
"""

from __future__ import annotations

import io
import json
import re

import frappe
from werkzeug.wrappers import Response

SCOPE = "/vansale"
ICON_SIZES = (192, 512)
DEFAULT_NAME = "Van Sale"
DEFAULT_THEME = "#2563eb"
BACKGROUND = "#f8fafc"

# Offline start: the app keeps its data in IndexedDB, and the worker keeps the
# built app files so the app opens (and every screen loads) without a
# connection. The page is fetched first (always the newest online; the last
# one offline). Built files carry a hash in their name, so a kept copy never
# goes stale; each build is kept in a cache of its own and older ones are
# dropped (a cached page of an old build used to 404 on its JS chunks).
def _shell_files() -> dict:
    """The built app's files under /assets/vansale/spa/ (offline start), and
    a version that changes with every build (a hash of the file names, which
    carry content hashes)."""
    import hashlib
    import os

    root = frappe.get_app_path("vansale", "public", "spa")
    files = []
    for folder, _dirs, names in os.walk(os.path.join(root, "assets")):
        for n in names:
            rel = os.path.relpath(os.path.join(folder, n), root).replace(os.sep, "/")
            files.append(f"/assets/vansale/spa/{rel}")
    files.sort()
    version = hashlib.sha1("\n".join(files).encode()).hexdigest()[:12]
    return {"version": version, "files": files}


SW_JS = """/* Van Sale service worker: makes the web app installable. */
const OFFLINE_HTML = '<!doctype html><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width,initial-scale=1">' +
  '<title>Van Sale</title><body style="font-family:sans-serif;padding:2rem;text-align:center">' +
  '<h2>No connection</h2><p>Connect to the internet and try again.</p></body>';

self.addEventListener("install", () => self.skipWaiting());

const SHELL_URL = "/vansale";
const PAGE_CACHE = "vansale-page";
const FILES_PREFIX = "vansale-files-";

/* Keep every file of the current build (listed by the server), then drop the
   caches of older builds. A file that fails is tried again on the next visit. */
async function keepAppFiles() {
  const res = await fetch("/vansale/shell-files.json", { cache: "no-store" });
  if (!res.ok) return;
  const list = await res.json();
  const name = FILES_PREFIX + list.version;
  const cache = await caches.open(name);
  for (const file of list.files || []) {
    if (await cache.match(file)) continue;
    try {
      await cache.add(file);
    } catch (e) {
      /* next visit */
    }
  }
  for (const key of await caches.keys()) {
    if (key.startsWith(FILES_PREFIX) && key !== name) await caches.delete(key);
  }
}
self.addEventListener("install", (event) => event.waitUntil(keepAppFiles().catch(() => {})));
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(
    fetch(event.request)
      .then((res) => {
        if (res.ok) {
          // The newest page is kept for an offline start, and the build's files with it.
          const copy = res.clone();
          event.waitUntil(
            caches.open(PAGE_CACHE).then((c) => c.put(SHELL_URL, copy)).then(keepAppFiles).catch(() => {}),
          );
        }
        return res;
      })
      .catch(() =>
        caches.match(SHELL_URL).then(
          (kept) => kept || new Response(OFFLINE_HTML, { headers: { "Content-Type": "text/html; charset=utf-8" } }),
        ),
      ),
  );
});

/* The app's built files: from the kept copy when there is one (offline, and
   a screen not opened yet), else the network. */
self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith("/assets/vansale/spa/")) return;
  event.respondWith(caches.match(req).then((kept) => kept || fetch(req)));
});

/* Web Push for approvals (vansale/steelforce/approvals_push.py). The payload
   is {title, body, url, tag}: a document's name at most, never its content. */
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = {};
  }
  if (!data || typeof data !== "object") data = {};
  event.waitUntil(
    self.registration.showNotification(data.title || "Approval needed", {
      body: data.body || "",
      tag: data.tag,
      data: { url: data.url || "/vansale/approvals" },
      icon: "/vansale/icon-192.png",
    }),
  );
});

/* A tap opens the document's approval screen. Only a path of this app is
   followed (same origin, under /vansale/): a payload can never send the
   phone anywhere else. */
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const origin = self.location.origin;
  let target = origin + "/vansale/approvals";
  try {
    const url = new URL((event.notification.data && event.notification.data.url) || "", origin);
    if (url.origin === origin && url.pathname.startsWith("/vansale/")) target = url.href;
  } catch (e) {
    /* not a URL: the approvals list it is */
  }
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const open = windows.find((w) => w.url.startsWith(origin + "/vansale"));
      if (open && typeof open.navigate === "function") {
        return open.navigate(target).then(
          (moved) => (moved || open).focus(),
          () => self.clients.openWindow(target),
        );
      }
      return self.clients.openWindow(target);
    }),
  );
});
"""


def _settings() -> dict:
    try:
        return frappe.db.get_singles_dict("Vansale Settings") or {}
    except Exception:
        return {}


def app_name() -> str:
    return (_settings().get("pwa_app_name") or "").strip() or DEFAULT_NAME


def theme_color() -> str:
    """The theme colour the SPA was built with (its <meta name="theme-color">)."""
    try:
        with open(frappe.get_app_path("vansale", "public", "spa", "index.html"), encoding="utf-8") as fh:
            m = re.search(r'name="theme-color"\s+content="([^"]+)"', fh.read())
        return m.group(1) if m else DEFAULT_THEME
    except OSError:
        return DEFAULT_THEME


def head_tags() -> str:
    """Tags added to the SPA page so browsers offer to install it."""
    name = frappe.utils.escape_html(app_name())
    return (
        f'<link rel="manifest" href="{SCOPE}/manifest.webmanifest">'
        # Tab icon; without one the browser asks for /favicon.ico (404).
        f'<link rel="icon" type="image/png" href="{SCOPE}/icon-192.png">'
        f'<link rel="apple-touch-icon" href="{SCOPE}/icon-192.png">'
        '<meta name="mobile-web-app-capable" content="yes">'
        '<meta name="apple-mobile-web-app-capable" content="yes">'
        f'<meta name="apple-mobile-web-app-title" content="{name}">'
    )


def _manifest() -> dict:
    name = app_name()
    icons = [
        {"src": f"{SCOPE}/icon-{s}.png", "sizes": f"{s}x{s}", "type": "image/png", "purpose": "any"}
        for s in ICON_SIZES
    ]
    icons.append(
        {"src": f"{SCOPE}/icon-512-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}
    )
    return {
        "id": SCOPE,
        "name": name,
        "short_name": name if len(name) <= 12 else name.split()[0][:12],
        "start_url": SCOPE,
        "scope": SCOPE,
        "display": "standalone",
        # Phones and tablets, either way up (a portrait lock kept tablets
        # from turning to landscape once installed).
        "orientation": "any",
        "background_color": BACKGROUND,
        "theme_color": theme_color(),
        "icons": icons,
    }


def _icon_source() -> bytes:
    """The configured icon's bytes, else the bundled default."""
    url = _settings().get("pwa_icon")
    if url:
        try:
            name = frappe.db.get_value("File", {"file_url": url}, "name")
            if name:
                return frappe.get_doc("File", name).get_content()
        except Exception:
            pass  # missing / unreadable file: fall back to the default icon
    with open(frappe.get_app_path("vansale", "public", "pwa", "icon.png"), "rb") as fh:
        return fh.read()


def _icon_png(size: int, maskable: bool) -> bytes:
    """Square PNG of `size`: the icon centred on a plain background (a logo
    of any shape fits). Maskable icons keep a wider margin, since launchers
    crop them to a circle or squircle."""
    from PIL import Image

    src = Image.open(io.BytesIO(_icon_source())).convert("RGBA")
    # A full-bleed square icon (like the default) is used as is; anything
    # else is a logo, placed on white with a margin.
    full_bleed = src.width == src.height and src.getpixel((0, 0))[3] == 255
    if full_bleed and not maskable:
        return _png(src.resize((size, size), Image.LANCZOS))

    bg = src.getpixel((0, 0)) if full_bleed else (255, 255, 255, 255)
    canvas = Image.new("RGBA", (size, size), bg)
    box = int(size * (0.8 if full_bleed else 0.64 if maskable else 0.84))
    src.thumbnail((box, box), Image.LANCZOS)
    canvas.alpha_composite(src, ((size - src.width) // 2, (size - src.height) // 2))
    return _png(canvas.convert("RGB"))


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _cached_icon(size: int, maskable: bool) -> bytes:
    s = _settings()
    key = f"vansale:pwa_icon:{s.get('pwa_icon') or 'default'}:{size}:{int(maskable)}"
    data = frappe.cache().get_value(key)
    if data is None:
        data = _icon_png(size, maskable)
        frappe.cache().set_value(key, data, expires_in_sec=24 * 3600)
    return data


_ICON_RE = re.compile(r"^/vansale/icon-(\d+)(-maskable)?\.png$")


class VansalePWARenderer:
    """Frappe `page_renderer` for the install files under /vansale.

    Route rules map every /vansale/<path> to the SPA page before renderers
    run, so this checks the real request path."""

    def __init__(self, path=None, http_status_code=None):
        self.path = frappe.local.request.path if getattr(frappe.local, "request", None) else ""

    def can_render(self) -> bool:
        p = self.path
        return p in (f"{SCOPE}/manifest.webmanifest", f"{SCOPE}/sw.js", f"{SCOPE}/shell-files.json") or bool(
            _ICON_RE.match(p)
        )

    def render(self) -> Response:
        p = self.path
        if p.endswith("manifest.webmanifest"):
            return Response(
                json.dumps(_manifest()),
                content_type="application/manifest+json",
                headers={"Cache-Control": "no-cache"},
            )
        if p.endswith("shell-files.json"):
            return Response(
                json.dumps(_shell_files()),
                content_type="application/json",
                headers={"Cache-Control": "no-cache"},
            )
        if p.endswith("sw.js"):
            return Response(
                SW_JS,
                content_type="application/javascript",
                # The worker lives at /vansale/sw.js but controls /vansale
                # itself (no trailing slash), one level above its folder.
                headers={"Service-Worker-Allowed": SCOPE, "Cache-Control": "no-cache"},
            )
        m = _ICON_RE.match(p)
        size = int(m.group(1))
        if size not in ICON_SIZES:
            return Response("Not found", status=404)
        return Response(
            _cached_icon(size, bool(m.group(2))),
            content_type="image/png",
            headers={"Cache-Control": "public, max-age=3600"},
        )
