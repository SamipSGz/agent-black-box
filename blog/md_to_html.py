"""Convert the tutorial markdown to a self-contained, print-ready HTML file.
Images are inlined as base64 so the resulting PDF needs no external files.
"""
import base64
import mimetypes
import pathlib
import re

import markdown

HERE = pathlib.Path(__file__).parent
SRC = HERE / "pre-event-signoz-tutorial.md"
OUT = HERE / "pre-event-signoz-tutorial.html"

text = SRC.read_text()
html_body = markdown.markdown(text, extensions=["fenced_code", "tables"])


def inline_image(match: re.Match) -> str:
    src = match.group(1)
    path = (HERE / src).resolve()
    if not path.exists():
        return match.group(0)
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode()
    return f'src="data:{mime};base64,{data}"'


html_body = re.sub(r'src="([^"]+)"', inline_image, html_body)

CSS = """
@page { size: A4; margin: 18mm 16mm; }
* { box-sizing: border-box; }
body { font: 12pt/1.6 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
       color: #1a1a1a; max-width: 100%; margin: 0; }
h1 { font-size: 22pt; line-height: 1.25; margin: 0 0 12pt; }
h2 { font-size: 15pt; margin: 20pt 0 8pt; border-bottom: 1px solid #e5e5e5; padding-bottom: 4pt; }
p { margin: 0 0 10pt; }
a { color: #0b66c3; text-decoration: none; }
code { font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 10.5pt;
       background: #f2f3f5; padding: 1px 4px; border-radius: 4px; }
pre { background: #0f1117; color: #e6e8ee; padding: 12pt; border-radius: 8px;
      overflow-x: auto; font-size: 9.5pt; line-height: 1.5; page-break-inside: avoid; }
pre code { background: none; color: inherit; padding: 0; font-size: 9.5pt; }
img { max-width: 100%; height: auto; border: 1px solid #e5e5e5; border-radius: 8px;
      margin: 8pt 0; page-break-inside: avoid; }
"""

html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Jumping from a log line to the exact trace that caused it</title>
<style>{CSS}</style></head><body>{html_body}</body></html>"""

OUT.write_text(html)
print(f"wrote {OUT}")
