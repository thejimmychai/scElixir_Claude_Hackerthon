#!/usr/bin/env python3
"""Build frontend/standalone.html — a single self-contained file.

Inlines the classic scripts (src/seed.js, api.js, state.js, stages.js, app.js)
into frontend/index.html so the app runs on a plain double-click (file://) with
no server and no build tooling, while still upgrading to the live backend when
one is reachable. Re-run this whenever the frontend source changes:

    python3 scripts/build_standalone.py
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FE = ROOT / "frontend"
SCRIPTS = ["src/seed.js", "src/api.js", "src/state.js", "src/stages.js", "src/app.js"]


def main() -> int:
    html = (FE / "index.html").read_text(encoding="utf-8")
    for src in SCRIPTS:
        code = (FE / src).read_text(encoding="utf-8")
        tag = '<script src="%s"></script>' % src
        if tag not in html:
            print(f"warning: expected script tag not found: {tag}", file=sys.stderr)
        html = html.replace(tag, "<script>\n/* inlined from %s */\n%s\n</script>" % (src, code))
    if 'script src="src/' in html:
        print("error: some external scripts were not inlined", file=sys.stderr)
        return 1
    html = html.replace(
        "<title>Universal Developmental Reprogramming Pipeline</title>",
        "<title>Universal Developmental Reprogramming Pipeline (standalone)</title>",
    )
    out = FE / "standalone.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
