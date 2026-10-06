"""SYS-96 / SYS-97 / SYS-102 end-to-end: drive the running search page in headless Chrome/Edge over the
DevTools protocol, as a reader would, with the keyboard only.

1. Tab through the start page: every stop is a visible, named control (the focus order is printed).
2. Type a question, press Enter: one turn, sources first, then the answer; focus lands on the question.
3. Ask a follow-up from the follow-up field: two turns on the page, same session.
4. Activate "Pertanyaan baru" with the keyboard: the thread is empty, the follow-up form is gone,
   focus is in the search box; the next question is sent with no session id.

Each question is one real model call (RAG_LLM_PROVIDER), counted under web:<model>.

    venv\\Scripts\\python.exe scripts\\experiments\\e2e_rag_page.py --base http://127.0.0.1:8765
"""
import argparse
import json
import os
import subprocess
import tempfile
import time
import urllib.request

import websocket

BROWSERS = (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
PORT = 9333


class Page:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=120, suppress_origin=True)
        self.n = 0

    def call(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    def js(self, expression):
        r = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    def key(self, key, code=None, shift=False, text=None):
        mods = 8 if shift else 0
        codes = {"Tab": 9, "Enter": 13, " ": 32}
        base = {"key": key, "code": code or key, "windowsVirtualKeyCode": codes.get(key, 0), "modifiers": mods}
        self.call("Input.dispatchKeyEvent", type="keyDown", **base, **({"text": text} if text else {}))
        self.call("Input.dispatchKeyEvent", type="keyUp", **base)

    def type(self, text):
        self.call("Input.insertText", text=text)

    def wait(self, expression, timeout=90):
        end = time.time() + timeout
        while time.time() < end:
            if self.js(expression):
                return True
            time.sleep(0.3)
        raise TimeoutError(expression)


FOCUSED = """(() => { const e = document.activeElement; if (!e) return null;
  const label = e.labels && e.labels[0] ? e.labels[0].innerText : '';
  const r = e.getBoundingClientRect();
  return [e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.type ? '[' + e.type + ']' : ''),
          (e.getAttribute('aria-label') || label || e.innerText || e.placeholder || e.value || '').trim().slice(0, 50),
          r.width > 0 && r.height > 0, getComputedStyle(e).outlineStyle !== 'none' || e.matches(':focus-visible')]; })()"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    args = ap.parse_args()
    browser = next(b for b in BROWSERS if os.path.exists(b))
    profile = tempfile.mkdtemp(prefix="e2e_rag_")
    proc = subprocess.Popen([browser, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
                             "--window-size=1280,1600", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                break
            except OSError:
                time.sleep(0.2)
        page = Page(next(t for t in targets if t["type"] == "page")["webSocketDebuggerUrl"])
        page.call("Page.enable")
        page.call("Page.navigate", url=args.base + "/")
        page.wait("document.readyState === 'complete' && !!window.htmx")
        results = []

        # 1. keyboard walk of the start page
        def walk(limit=30):
            page.js("document.activeElement && document.activeElement.blur(); document.body.focus()")
            out = []
            for _ in range(limit):
                page.key("Tab")
                stop = page.js(FOCUSED)
                if stop is None or stop[0] == "body":     # the browser wrapped around the page
                    break
                out.append(stop)
            return out

        stops = walk()
        print("Tab order on the start page (filters closed):")
        for s in stops:
            print("  ", s)
        # open "Filter" with the keyboard, then walk again: the filter controls join the order
        page.js("document.querySelector('#filters summary').focus()")
        page.key(" ", code="Space", text=" ")
        results.append(("Space on 'Filter' opens the panel", page.js("document.getElementById('filters').open"), ""))
        opened = walk()
        print("Tab order with the filter panel open:")
        for s in opened:
            print("  ", s)
        stops += opened
        results.append(("the filter controls are reachable",
                        all(any(s[0].startswith(t) for s in opened) for t in ("select#filter-topic", "select#filter-source", "input[radio]")),
                        ""))
        unnamed = [s for s in stops if s and not s[1]]
        hidden = [s for s in stops if s and not s[2]]
        results.append(("every tab stop is named", not unnamed, unnamed))
        results.append(("every tab stop is visible", not hidden, hidden))

        # 2. ask with the keyboard
        page.js("document.getElementById('query-input').focus()")
        page.type("Kenapa rupiah melemah pekan ini?")
        page.key("Enter", text="\r")
        page.wait("document.querySelectorAll('#thread .turn').length === 1 && !!document.querySelector('#thread .card')")
        cards_first = page.js("document.querySelectorAll('#thread .card').length")
        page.wait("!document.querySelector('#thread .answer [hx-trigger]')")
        results.append(("one turn with sources, then an answer", True, f"{cards_first} cards"))
        results.append(("focus moves to the new question",
                        page.js("document.activeElement && document.activeElement.classList.contains('turn-q')"), ""))
        sid1 = page.js("(document.querySelector('#followup [name=session_id]')||{}).value")
        results.append(("the indicator is hidden at rest",
                        page.js("getComputedStyle(document.getElementById('search-status')).display") == "none", ""))
        cite = page.js("(document.querySelector('#thread a.cite')||{}).getAttribute ? "
                       "document.querySelector('#thread a.cite').getAttribute('href') : null")
        target_exists = page.js(f"!!document.querySelector({json.dumps(cite)})") if cite else None
        results.append(("a citation points at a card on the page", bool(target_exists), cite))

        # 3. follow-up from its own field
        page.js("document.getElementById('followup-input').focus()")
        page.type("Apa kata Bank Indonesia soal itu?")
        page.key("Enter", text="\r")
        page.wait("document.querySelectorAll('#thread .turn').length === 2")
        page.wait("!document.querySelector('#thread .answer [hx-trigger]')")
        sid2 = page.js("(document.querySelector('#followup [name=session_id]')||{}).value")
        results.append(("a follow-up appends (2 turns) in the same session", sid1 and sid1 == sid2, f"{sid1} / {sid2}"))

        # 4. "Pertanyaan baru" with the keyboard
        page.js("document.getElementById('new-question').focus()")
        page.key("Enter", text="\r")
        page.wait("document.querySelectorAll('#thread .turn').length === 0")
        results.append(("Pertanyaan baru empties the thread", True, ""))
        results.append(("the follow-up form is gone", page.js("!document.querySelector('#followup form, form#followup')"), ""))
        results.append(("focus is in the search box", page.js("document.activeElement.id === 'query-input'"), ""))
        results.append(("the search form sends no session id",
                        page.js("!document.querySelector('#search-form [name=session_id]')"), ""))
        results.append(("the hero is back", page.js("getComputedStyle(document.querySelector('.hero')).display !== 'none'"), ""))

        print()
        for name, ok, detail in results:
            print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail or ''}")
        failed = [r for r in results if not r[1]]
        print(f"\n{len(results) - len(failed)}/{len(results)} passed")
        raise SystemExit(1 if failed else 0)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
