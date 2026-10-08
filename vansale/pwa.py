"""Install support for the web app ("Add to Home screen").

Served under /vansale, so the installed app and its service worker cover only
the van-sales screens. Frappe sites may already serve another app's worker
at /sw.js (POS Awesome on Badria); registering that one made the phone see
POS Awesome's manifest, and Van Sale had none, so it could not be installed.

  /vansale/manifest.webmanifest  name, icons, start URL, standalone display
  /vansale/sw.js                 service worker (no caching, see SW_JS)
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

# No caching on purpose: the app keeps its offline data in IndexedDB, and a
# cached app shell outlives a rebuild (old JS chunk names 404). Navigations
# go to the network, with a short message when there is none.
SW_JS = """/* Van Sale service worker: makes the web app installable. */
const OFFLINE_HTML = '<!doctype html><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width,initial-scale=1">' +
  '<title>Van Sale</title><body style="font-family:sans-serif;padding:2rem;text-align:center">' +
  '<h2>No connection</h2><p>Connect to the internet and try again.</p></body>';

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(
    fetch(event.request).catch(
      () => new Response(OFFLINE_HTML, { headers: { "Content-Type": "text/html; charset=utf-8" } }),
    ),
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
        "orientation": "portrait",
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
        return p in (f"{SCOPE}/manifest.webmanifest", f"{SCOPE}/sw.js") or bool(_ICON_RE.match(p))

    def render(self) -> Response:
        p = self.path
        if p.endswith("manifest.webmanifest"):
            return Response(
                json.dumps(_manifest()),
                content_type="application/manifest+json",
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
