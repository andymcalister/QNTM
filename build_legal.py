#!/usr/bin/env python3
"""
build_legal.py — regenerate the static legal pages from app.py's canonical policy
strings so the public static pages (served by the Render "legal" static site) can
never drift from the in-app versions.

This is wired into the static site's Build Command:

    pip install markdown && python build_legal.py

Writes:  legal/privacy.html, legal/terms.html
Source:  PRIVACY_POLICY and TERMS_OF_SERVICE in app.py.

app.py is read as TEXT and the policy strings are extracted by regex — app.py is
never imported, so none of the Streamlit runtime (streamlit, pandas, yfinance, ...)
is needed at build time. The static build stays light and fast.
"""
import re
import sys
import pathlib

APP = pathlib.Path("app.py")
OUT = pathlib.Path("legal")

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — QNTM LLC</title>
<meta name="description" content="{desc}">
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
       max-width:760px;margin:0 auto;padding:40px 20px;color:#1a1a1a;line-height:1.65;}}
  h1,h2,h3{{line-height:1.25;}} h2{{margin-top:32px;border-bottom:1px solid #eee;padding-bottom:6px;}}
  h3{{margin-top:24px;}}
  table{{border-collapse:collapse;width:100%;margin:16px 0;font-size:14px;}}
  th,td{{border:1px solid #ddd;padding:8px 10px;text-align:left;}} th{{background:#f7f7f7;}}
  code{{background:#f2f2f2;padding:1px 4px;border-radius:3px;}}
  a{{color:#0a7;}} strong{{color:#000;}}
  footer{{margin-top:40px;padding-top:16px;border-top:1px solid #eee;font-size:13px;color:#777;}}
</style>
</head>
<body>
{body}
<footer>QNTM LLC · 35 Laguna Woods Drive, Laguna Niguel, CA 92677 · privacy@qntm.live</footer>
</body>
</html>
"""


def extract(src: str, var: str) -> str:
    """Pull a triple-quoted module constant out of app.py source text."""
    m = re.search(var + r'\s*=\s*"""(.*?)"""', src, re.S)
    if not m:
        sys.exit(f"ERROR: {var} not found in app.py — aborting (static pages NOT overwritten).")
    body = m.group(1).strip()
    if not body:
        sys.exit(f"ERROR: {var} is empty in app.py — aborting (static pages NOT overwritten).")
    return body


def render_md(md: str) -> str:
    try:
        import markdown
    except ImportError:
        sys.exit("ERROR: 'markdown' not installed. Build Command must be: "
                 "pip install markdown && python build_legal.py")
    return markdown.markdown(md, extensions=["tables"])


def build(src: str, var: str, fname: str, title: str, desc: str) -> None:
    html = TEMPLATE.format(title=title, desc=desc, body=render_md(extract(src, var)))
    path = OUT / fname
    path.write_text(html)
    # Sanity guards: refuse to publish a page missing its required A2P clause.
    required = "never shared with, sold, or rented"
    if fname == "terms.html":
        required = "Reply <strong>STOP"
    if required not in html:
        sys.exit(f"ERROR: {fname} is missing the required A2P clause "
                 f"('{required}') — aborting so a non-compliant page isn't published.")
    print(f"wrote {path} ({len(html)} bytes) — A2P clause present")


def main() -> None:
    if not APP.exists():
        sys.exit("ERROR: app.py not found — run build_legal.py from the repo root.")
    OUT.mkdir(exist_ok=True)
    src = APP.read_text()
    build(src, "PRIVACY_POLICY", "privacy.html", "Privacy Policy",
          "QNTM LLC Privacy Policy, including SMS/text message alert data practices.")
    build(src, "TERMS_OF_SERVICE", "terms.html", "Terms of Service",
          "QNTM LLC Terms of Service, including SMS/text message program terms.")
    print("Static legal pages regenerated from app.py. Single source of truth: app.py.")


if __name__ == "__main__":
    main()
