"""SYS-102 (#271): screenshots of the running search page at 375 px and 1280 px, light and dark.

Headless browsers capture a page's first state only, so the answered state is a snapshot:
the real index page with the real fragments the server returned for a question (the turn,
then its answer) put into the thread, saved as one HTML file that loads the server's own
stylesheet. Then headless Edge (or Chrome) captures each file at each width and theme.

    venv\\Scripts\\python.exe scripts\\experiments\\snapshot_rag_page.py --base http://127.0.0.1:8765 \\
        --question "Kenapa rupiah melemah pekan ini?" --out <dir>
"""
import argparse
import os
import re
import subprocess
import urllib.parse
import urllib.request

BROWSERS = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def _get(url):
    with urllib.request.urlopen(url, timeout=600) as r:
        return r.read().decode("utf-8")


def _post(url, data=None):
    body = urllib.parse.urlencode(data or {}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"HX-Request": "true"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read().decode("utf-8")


def answered_page(base, question, **filters):
    index = _get(f"{base}/")
    turn = _post(f"{base}/api/query/form", {"query": question, **filters})
    turn_id = re.search(r'/api/answer/([0-9a-f]+)', turn)
    if turn_id:
        answer = _post(f"{base}/api/answer/{turn_id.group(1)}")
        # The placeholder div is what htmx would replace with the answer's inner HTML.
        turn = re.sub(r'<div hx-post="/api/answer/[^"]+".*?</div>', answer, turn, count=1, flags=re.S)
    followup = re.search(r'<form id="followup".*?</form>', turn, re.S)
    article = re.search(r'<article.*?</article>', turn, re.S).group(0)
    page = index.replace('<div id="thread"></div>', f'<div id="thread">{article}</div>')
    if followup:
        page = page.replace('<div id="followup"></div>', followup.group(0))
    return page


def absolute(page, base):
    return page.replace('href="/static/', f'href="{base}/static/').replace('src="/static/', f'src="{base}/static/')


MIN_WINDOW = 500   # new-mode headless Chrome/Edge will not lay a window out narrower than ~500 px


def shoot(html_path, png_path, width, dark):
    browser = next(b for b in BROWSERS if os.path.exists(b))
    if width < MIN_WINDOW:
        # A phone width is a 375 px iframe in a wider window: the iframe is the page's viewport,
        # so its media queries and prefers-color-scheme behave as on the phone.
        frame = html_path.replace(".html", f"_frame{width}.html")
        with open(frame, "w", encoding="utf-8") as fh:
            fh.write(f'<!doctype html><body style="margin:0"><iframe src="{os.path.basename(html_path)}" '
                     f'style="border:0;width:{width}px;height:2400px"></iframe></body>')
        html_path, window = frame, MIN_WINDOW
    else:
        window = width
    args = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={window},2400",
            f"--screenshot={png_path}", "--virtual-time-budget=4000"]
    if dark:
        args += ["--force-dark-mode", "--blink-settings=preferredColorScheme=0"]
    subprocess.run(args + ["file:///" + html_path.replace("\\", "/")], check=True, capture_output=True, timeout=120)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--question", default="Kenapa rupiah melemah pekan ini?")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    pages = {"hero": _get(f"{args.base}/"), "answered": answered_page(args.base, args.question)}
    for name, page in pages.items():
        html_path = os.path.abspath(os.path.join(args.out, f"{name}.html"))
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(absolute(page, args.base))
        for width in (375, 1280):
            for dark in (False, True):
                png = os.path.join(os.path.abspath(args.out), f"{name}_{width}_{'dark' if dark else 'light'}.png")
                shoot(html_path, png, width, dark)
                print(png)


if __name__ == "__main__":
    main()
