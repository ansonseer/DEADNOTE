#!/usr/bin/env python3
"""Build the handbook into one offline HTML file and (optionally) a PDF.

Usage:
    python3 build.py            # -> dist/ai-native-handbook.html
    python3 build.py --pdf      # also -> dist/ai-native-handbook.pdf (needs Chromium)

Reads manifest.json for chapter order. Each chapter is a markdown file under chapters/.
"""
import json, os, re, sys, subprocess, shutil, html
import markdown

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "dist")
MANIFEST = os.path.join(HERE, "manifest.json")

CSS = """
:root{--fg:#1b1b1f;--bg:#fffdf8;--muted:#5c5c66;--line:#e3ded2;--accent:#8a3b12;--code:#f3efe6}
@media (prefers-color-scheme: dark){:root{--fg:#e8e6e0;--bg:#15151a;--muted:#a3a1a8;--line:#2d2d36;--accent:#e0925f;--code:#20202a}}
html{font-size:16px}
body{margin:0;background:var(--bg);color:var(--fg);font-family:"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Source Han Sans SC","WenQuanYi Zen Hei","Microsoft YaHei",system-ui,sans-serif;line-height:1.75}
.wrap{max-width:46rem;margin:0 auto;padding:2rem 1.25rem 6rem}
h1,h2,h3,h4{line-height:1.3;font-weight:700}
h1{font-size:1.9rem;margin:3rem 0 1rem;border-bottom:2px solid var(--line);padding-bottom:.4rem}
h2{font-size:1.4rem;margin:2.4rem 0 .8rem}
h3{font-size:1.15rem;margin:1.8rem 0 .6rem}
h4{font-size:1rem;margin:1.4rem 0 .4rem;color:var(--muted)}
p{margin:.8rem 0}
li{margin:.3rem 0}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"WenQuanYi Zen Hei Mono",monospace;font-size:.9em;background:var(--code);padding:.1em .35em;border-radius:4px}
pre{background:var(--code);padding:.9rem 1rem;border-radius:8px;overflow-x:auto;line-height:1.5}
pre code{background:none;padding:0;font-size:.85em}
blockquote{margin:1rem 0;padding:.4rem 1rem;border-left:4px solid var(--accent);color:var(--muted);background:var(--code)}
table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.92em;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:.45rem .6rem;text-align:left;vertical-align:top}
th{background:var(--code)}
hr{border:0;border-top:1px solid var(--line);margin:2.5rem 0}
a{color:var(--accent)}
.toc{background:var(--code);padding:1rem 1.25rem;border-radius:10px;margin:1rem 0 3rem}
.toc ol{margin:0;padding-left:1.4rem}
.toc .part{font-weight:700;margin:.8rem 0 .3rem;list-style:none;margin-left:-1.4rem;color:var(--muted)}
.chapter{page-break-before:always;break-before:page}
.chapter:first-of-type{page-break-before:auto;break-before:auto}
.meta{color:var(--muted);font-size:.9em}
@media print{html{font-size:11.5pt}.wrap{max-width:none;padding:0}a{color:inherit;text-decoration:none}pre{white-space:pre-wrap}}
"""

def slug(s):
    return re.sub(r"[^\w一-鿿-]+", "-", s.strip()).strip("-").lower()

def render(md_text):
    return markdown.markdown(
        md_text,
        extensions=["extra", "toc", "sane_lists", "admonition", "pymdownx.superfences", "pymdownx.tilde"],
        extension_configs={"toc": {"permalink": False}},
        output_format="html5",
    )

def main():
    want_pdf = "--pdf" in sys.argv
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    os.makedirs(DIST, exist_ok=True)

    parts_html = []
    toc_items = []
    current_part = None
    total_chars = 0
    for ch in manifest["chapters"]:
        path = os.path.join(HERE, "chapters", ch["file"])
        if not os.path.exists(path):
            print(f"[warn] missing {ch['file']}", file=sys.stderr)
            continue
        with open(path, encoding="utf-8") as f:
            md_text = f.read()
        total_chars += len(md_text)
        anchor = "ch-" + ch["id"]
        if ch.get("part") != current_part:
            current_part = ch.get("part")
            toc_items.append(f'<li class="part">{html.escape(current_part or "")}</li>')
        toc_items.append(f'<li><a href="#{anchor}">{html.escape(ch["id"])} · {html.escape(ch["title"])}</a> <span class="meta">≈{ch.get("est_minutes", "?")} 分钟</span></li>')
        body = render(md_text)
        parts_html.append(f'<section class="chapter" id="{anchor}">{body}</section>')

    front = manifest.get("front_matter_file")
    front_html = ""
    if front and os.path.exists(os.path.join(HERE, front)):
        with open(os.path.join(HERE, front), encoding="utf-8") as f:
            front_html = render(f.read())

    title = manifest.get("title", "AI-Native Handbook")
    doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style></head>
<body><div class="wrap">
<section class="front">{front_html}</section>
<nav class="toc"><strong>目录</strong><ol>{''.join(toc_items)}</ol></nav>
{''.join(parts_html)}
</div></body></html>"""
    out_html = os.path.join(DIST, "ai-native-handbook.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"wrote {out_html} ({total_chars} md chars across chapters)")

    if want_pdf:
        chrome = shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("chrome")
        if not chrome:
            cands = sorted(__import__("glob").glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))
            chrome = cands[-1] if cands else None
        if not chrome:
            print("[warn] no chromium found; skipping PDF", file=sys.stderr)
            return
        out_pdf = os.path.join(DIST, "ai-native-handbook.pdf")
        cmd = [chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
               f"--print-to-pdf={out_pdf}", "file://" + out_html]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
        print(f"wrote {out_pdf}")

if __name__ == "__main__":
    main()
