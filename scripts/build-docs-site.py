#!/usr/bin/env python3
"""Build the static docs site served at vansales.docs.enfonoerp.com.

Renders the hand-written markdown in docs/ plus the generated reference/ into a
multi-page HTML site with a shared shell, and copies the user guide (which is
already a styled standalone page) in beside them.

    python3 scripts/gen-docs.py        # refresh reference/ from source first
    python3 scripts/build-docs-site.py # then build the site
    # output: dist/docs-site/

Design tokens are duplicated from docs/userguide/index.html on purpose: the site
must render with no network access at all (the docs box serves static files and
nothing else), so there is no shared stylesheet to fetch and no font CDN.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import markdown

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = ROOT / "dist" / "docs-site"

# (source markdown, output path, nav label, nav group)
PAGES = [
    (DOCS / "README.md", "index.html", "Overview", "Start"),
    (DOCS / "ARCHITECTURE.md", "architecture.html", "Architecture", "Engineering"),
    (DOCS / "OPERATIONS.md", "operations.html", "Operations", "Engineering"),
    (DOCS / "SECURITY.md", "security.html", "Security", "Engineering"),
    (DOCS / "reference" / "API.md", "reference/api.html", "API", "Reference"),
    (DOCS / "reference" / "DOCTYPES.md", "reference/doctypes.html", "DocTypes", "Reference"),
    (DOCS / "reference" / "HOOKS.md", "reference/hooks.html", "Hooks", "Reference"),
]
GUIDE = ("userguide/index.html", "User guide", "Start")

CSS = """
:root{--accent:#2563eb;--accent-deep:#1b3fa8;--accent-soft:#e8eeff;--ink:#131a24;
--ink-2:#3d4a5a;--muted:#5a6673;--line:#dde3ea;--line-soft:#eaeef4;--paper:#f6f8fb;
--surface:#fff;--warn:#a85c00;--warn-soft:#fdf3e3;--crit:#b3261e;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
--mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;--measure:72ch;--r:8px}
@media (prefers-color-scheme:dark){:root{--accent:#6d9bff;--accent-deep:#a8c2ff;
--accent-soft:#17233a;--ink:#e6ebf2;--ink-2:#bcc7d6;--muted:#8e9cad;--line:#263243;
--line-soft:#1d2734;--paper:#0e141b;--surface:#161e28;--warn:#e0a252;--warn-soft:#2a2013;
--crit:#f2837b}}
:root[data-theme=dark]{--accent:#6d9bff;--accent-deep:#a8c2ff;--accent-soft:#17233a;
--ink:#e6ebf2;--ink-2:#bcc7d6;--muted:#8e9cad;--line:#263243;--line-soft:#1d2734;
--paper:#0e141b;--surface:#161e28;--warn:#e0a252;--warn-soft:#2a2013;--crit:#f2837b}
:root[data-theme=light]{--accent:#2563eb;--accent-deep:#1b3fa8;--accent-soft:#e8eeff;
--ink:#131a24;--ink-2:#3d4a5a;--muted:#5a6673;--line:#dde3ea;--line-soft:#eaeef4;
--paper:#f6f8fb;--surface:#fff;--warn:#a85c00;--warn-soft:#fdf3e3;--crit:#b3261e}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
font-size:16px;line-height:1.65;-webkit-font-smoothing:antialiased}
a{color:var(--accent)}
.top{border-bottom:1px solid var(--line);background:var(--surface);position:sticky;top:0;z-index:10}
.top-in{max-width:1240px;margin:0 auto;padding:.75rem 1.25rem;display:flex;
align-items:center;justify-content:space-between;gap:1rem}
.brand{display:flex;align-items:center;gap:.6rem;text-decoration:none;color:var(--ink);font-weight:700;letter-spacing:-.01em}
.brand .mk{width:1.6rem;height:1.6rem;border-radius:6px;background:var(--accent);color:#fff;
display:grid;place-items:center;font-size:.8rem}
.top .ver{font-family:var(--mono);font-size:.72rem;color:var(--muted);border:1px solid var(--line);
border-radius:6px;padding:.15rem .45rem}
.wrap{max-width:1240px;margin:0 auto;padding:0 1.25rem 6rem;display:grid;
grid-template-columns:224px minmax(0,1fr);gap:3rem;align-items:start}
@media(max-width:900px){.wrap{grid-template-columns:minmax(0,1fr);gap:0}
.side{position:static;border-inline-end:0;border-bottom:1px solid var(--line);
margin:1rem 0 2rem;padding-bottom:1rem}}
.side{position:sticky;top:4.5rem;padding:2rem 1rem 0 0;border-inline-end:1px solid var(--line-soft);font-size:.9rem}
.side h2{font-size:.66rem;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:1.25rem 0 .4rem}
.side h2:first-child{margin-top:0}
.side ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:.1rem}
.side a{display:block;color:var(--ink-2);text-decoration:none;padding:.25rem .5rem;border-radius:6px}
.side a:hover{color:var(--accent);background:var(--accent-soft)}
.side a[aria-current=page]{color:var(--accent);background:var(--accent-soft);font-weight:650}
main{min-width:0;padding-top:2rem}
main>*{max-width:var(--measure)}
h1{font-size:clamp(1.9rem,4.5vw,2.6rem);line-height:1.1;letter-spacing:-.03em;margin:0 0 1rem;text-wrap:balance}
h2{font-size:clamp(1.25rem,2.6vw,1.55rem);letter-spacing:-.02em;margin:2.5rem 0 .75rem;
padding-top:1.25rem;border-top:1px solid var(--line);text-wrap:balance}
h3{font-size:1.08rem;margin:1.75rem 0 .5rem;letter-spacing:-.01em}
h4{font-size:.95rem;margin:1.25rem 0 .4rem;color:var(--ink-2)}
p,ul,ol{margin:0 0 1rem}
ul,ol{padding-inline-start:1.3rem}
li{margin-bottom:.3rem}
code{font-family:var(--mono);font-size:.855em;background:var(--accent-soft);
color:var(--accent-deep);padding:.1em .35em;border-radius:4px;word-break:break-word}
pre{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
padding:.9rem 1rem;overflow-x:auto;max-width:100%}
pre code{background:none;color:var(--ink);padding:0;font-size:.82rem;line-height:1.55}
blockquote{margin:0 0 1rem;padding:.85rem 1.1rem;border:1px solid var(--line);
border-inline-start:3px solid var(--warn);background:var(--warn-soft);border-radius:var(--r)}
blockquote p:last-child{margin-bottom:0}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:var(--r);
background:var(--surface);margin:0 0 1.25rem;max-width:100%}
table{border-collapse:collapse;width:100%;font-size:.89rem}
th,td{text-align:start;padding:.6rem .8rem;border-bottom:1px solid var(--line-soft);vertical-align:top}
th{font-size:.67rem;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);
background:var(--paper);white-space:nowrap;font-weight:650}
tbody tr:last-child td{border-bottom:0}
td code{white-space:nowrap}
hr{border:0;border-top:1px solid var(--line);margin:2rem 0}
.genwarn{font-family:var(--mono);font-size:.75rem;color:var(--warn);
background:var(--warn-soft);border:1px solid color-mix(in srgb,var(--warn) 30%,transparent);
border-radius:var(--r);padding:.5rem .75rem;margin:0 0 1.5rem}
footer{max-width:1240px;margin:0 auto;padding:2rem 1.25rem 3rem;border-top:1px solid var(--line);
color:var(--muted);font-size:.82rem;display:flex;flex-wrap:wrap;gap:.5rem 1.5rem;justify-content:space-between}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""


def version() -> str:
    for cmd in (["git", "describe", "--tags", "--abbrev=0"], ["git", "rev-parse", "--short", "HEAD"]):
        try:
            v = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
            if v:
                return v
        except Exception:
            continue
    return ""


def nav_html(active: str) -> str:
    groups: dict = {}
    for src, out, label, group in PAGES:
        groups.setdefault(group, []).append((out, label))
    groups.setdefault(GUIDE[2], []).insert(0, (GUIDE[0], GUIDE[1]))

    parts = []
    for group in ("Start", "Engineering", "Reference"):
        if group not in groups:
            continue
        parts.append(f"<h2>{group}</h2><ul>")
        for out, label in groups[group]:
            depth = active.count("/")
            href = ("../" * depth) + out
            cur = ' aria-current="page"' if out == active else ""
            parts.append(f'<li><a href="{href}"{cur}>{label}</a></li>')
        parts.append("</ul>")
    return "".join(parts)


def rewrite_links(html: str, depth: int) -> str:
    """Point in-repo markdown links at the built pages."""
    mapping = {
        "userguide/index.html": "userguide/index.html",
        "ARCHITECTURE.md": "architecture.html",
        "OPERATIONS.md": "operations.html",
        "SECURITY.md": "security.html",
        "README.md": "index.html",
        "reference/API.md": "reference/api.html",
        "reference/DOCTYPES.md": "reference/doctypes.html",
        "reference/HOOKS.md": "reference/hooks.html",
        "reference/": "reference/api.html",
        "API.md": "api.html",
        "DOCTYPES.md": "doctypes.html",
        "HOOKS.md": "hooks.html",
    }
    up = "../" * depth
    for src, dst in mapping.items():
        target = dst if depth == 0 else (dst if src in ("API.md", "DOCTYPES.md", "HOOKS.md") else up + dst)
        html = html.replace(f'href="{src}"', f'href="{target}"')
    # Repo-relative source links have no meaning on the docs site.
    html = re.sub(
        r'<a href="(?!https?:|#|\.\./|[a-z]+\.html|reference/|userguide/)[^"]+\.(py|ts|vue|json|md)">([^<]*)</a>',
        r"<code>\2</code>",
        html,
    )
    return html


def render(md_path: pathlib.Path, out_rel: str, ver: str) -> str:
    raw = md_path.read_text()
    generated = "GENERATED BY scripts/gen-docs.py" in raw
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)

    body = markdown.markdown(
        raw,
        extensions=["tables", "fenced_code", "sane_lists", "attr_list", "toc"],
        output_format="html5",
    )
    body = body.replace("<table>", '<div class="tablewrap"><table>').replace("</table>", "</table></div>")
    depth = out_rel.count("/")
    body = rewrite_links(body, depth)

    if generated:
        body = (
            '<p class="genwarn">Generated from source by <code>scripts/gen-docs.py</code>'
            " — do not edit by hand.</p>" + body
        )

    up = "../" * depth
    title = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    page_title = re.sub(r"<[^>]+>", "", title.group(1)).strip() if title else "Van Sale docs"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{page_title} · Van Sale docs</title>
<style>{CSS}</style>
</head>
<body>
<div class="top"><div class="top-in">
  <a class="brand" href="{up}index.html"><span class="mk">V</span> Van Sale documentation</a>
  <span class="ver">{ver}</span>
</div></div>
<div class="wrap">
  <nav class="side" aria-label="Documentation">{nav_html(out_rel)}</nav>
  <main>{body}</main>
</div>
<footer>
  <span>Confidential — Enfono Technologies</span>
  <span>vansales.docs.enfonoerp.com</span>
</footer>
</body>
</html>
"""


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "reference").mkdir(parents=True, exist_ok=True)
    ver = version()

    for src, out_rel, _label, _group in PAGES:
        if not src.exists():
            print(f"  skip (missing): {src}")
            continue
        (OUT / out_rel).write_text(render(src, out_rel, ver))
        print(f"  {out_rel:28} <- {src.relative_to(ROOT)}")

    guide_src = DOCS / "userguide" / "index.html"
    guide_out = OUT / "userguide"
    guide_out.mkdir(parents=True, exist_ok=True)
    head = (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
    )
    (guide_out / "index.html").write_text(head + guide_src.read_text() + "\n</html>\n")
    print(f"  userguide/index.html         <- {guide_src.relative_to(ROOT)}")

    img = DOCS / "userguide" / "img"
    if img.exists() and any(img.iterdir()):
        shutil.copytree(img, guide_out / "img", dirs_exist_ok=True)
        print(f"  userguide/img/               <- {len(list(img.iterdir()))} file(s)")

    # noindex is belt; robots.txt is braces. A client-preview docs host must not
    # be crawlable — see the hbrc incident in the enfono-servers LIVE_STATE.
    (OUT / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    print("  robots.txt                   <- Disallow: /")
    print(f"\nbuilt {ver} -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
