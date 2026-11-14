"""Per-ticket ledger and the deterministic half of the dev/QA contract (OPS-50).

The /implement-issue and /qa-issue skills call this; so do the Stop hook and
the git commit-msg hook. Rules live in .claude/qa-rules.md and CLAUDE.md
("Definition of done"); this file only parses, runs and checks.

  ticket.py show <ref>                 issue + ledger (+ ready-for-qa queue size)
  ticket.py init <ref>                 create tickets/<ID>.md from the issue's AC lines
                                       (legacy ticket: from its Done-when)
  ticket.py verify <ref>               run the ledger's Verify command, exit with its code
  ticket.py dev-start <ref>            arm the Stop hook for this ticket
  ticket.py dev-stop                   disarm it
  ticket.py stop-hook                  Claude Code Stop hook (reads the hook JSON on stdin)
  ticket.py check-commit-msg <file>    git commit-msg hook: no auto-closing keywords

<ref> is a ticket ID (SYS-152), a GitHub number (342) or #342.
"""
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TICKETS_DIR = "tickets"
STATE_DIR = Path(".claude") / "state"
MARKER = "active-ticket.json"
MAX_ROUNDS = 3
MAX_FORCED_CONTINUES = 3
MARKER_MAX_AGE_H = 24
VERIFY_TIMEOUT_S = 540
WATCHED_PATHS = ["newscrawler", "scripts", "tests", "__main__.py"]

ID_RE = re.compile(r"^\[([A-Z]+-\d+)\]")
AC_RE = re.compile(
    r"^\s*(?:[-*]\s+)?(?:\[[ xX]\]\s*)?\**AC(\d+)\**\s*(\[[^\]]+\])?\s*\**\s*:\**\s*(.+?)\s*$"
)
HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*$")
FIELD_RE = re.compile(r"^[-*]\s+\*\*([^*:]+):?\*\*:?\s*(.*)$")
CLOSING_RE = re.compile(
    r"\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+(?:[\w.-]+/[\w.-]+)?#\d+", re.IGNORECASE
)


# ---------------------------------------------------------------- GitHub


def _gh():
    return shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"


def _gh_json(args):
    out = subprocess.run([_gh(), *args], capture_output=True, check=True, cwd=ROOT)
    return json.loads(out.stdout.decode("utf-8"))


def resolve(ref):
    """Return (number, ticket_id) for a ticket ID or GitHub number."""
    ref = ref.strip().lstrip("#")
    if ref.isdigit():
        issue = _gh_json(["issue", "view", ref, "--json", "number,title"])
        return issue["number"], ticket_id(issue["title"], issue["number"])
    hits = _gh_json(
        ["issue", "list", "--state", "all", "--search", f"[{ref}] in:title", "--json", "number,title"]
    )
    for issue in hits:
        if issue["title"].startswith(f"[{ref}]"):
            return issue["number"], ref
    raise SystemExit(f"ticket.py: no issue titled [{ref}]")


def ticket_id(title, number):
    m = ID_RE.match(title)
    return m.group(1) if m else f"ISSUE-{number}"


# ---------------------------------------------------------------- parsing


def _sections(body):
    """Map a lower-cased heading/field name to its lines.

    Understands '## Heading' sections and the templates' '- **Field:** text' lines.
    """
    sections, current = {}, None
    for line in body.splitlines():
        h = HEADING_RE.match(line)
        f = FIELD_RE.match(line)
        if h:
            current = h.group(1).strip().rstrip(":").lower()
            sections[current] = []
        elif f:
            current = f.group(1).strip().lower()
            sections[current] = [f.group(2)] if f.group(2).strip() else []
        elif current is not None:
            sections[current].append(line)
    return sections


def _find(sections, *names):
    for key, lines in sections.items():
        if any(key.startswith(n) for n in names):
            return lines
    return []


def parse_acceptance(body):
    """[(id, kind, text)] from 'AC<n> [kind]: text' lines; indented lines continue the AC above."""
    found, current = [], None
    for line in body.splitlines():
        m = AC_RE.match(line)
        if m:
            current = [f"AC{m.group(1)}", (m.group(2) or "[?]").strip("[]"), m.group(3).strip()]
            found.append(current)
        elif current and line[:1].isspace() and line.strip():
            current[2] += " " + re.sub(r"^\s*[-*]\s+", "", line).strip()
        else:
            current = None
    return [tuple(f) for f in found]


def parse_done_when(body):
    """Legacy tickets: each top-level Done-when item becomes one criterion."""
    items = []
    for line in _find(_sections(body), "done when"):
        if not line.strip():
            continue
        top = re.match(r"^[-*]\s+(?:\[[ xX]\]\s*)?(.+)$", line)
        if top:
            items.append(top.group(1).strip())
        elif items:
            items[-1] += "; " + re.sub(r"^\s*[-*]\s+", "", line).strip()
        else:
            items.append(line.strip())
    return [(f"AC{i}", "?", text) for i, text in enumerate(items, 1)]


def parse_verify(text):
    for line in _find(_sections(text), "verify"):
        line = line.strip()
        if line:
            return line.strip("`").strip()
    return None


def parse_out_of_scope(body):
    return [l.strip() for l in _find(_sections(body), "out of scope") if l.strip()]


# ---------------------------------------------------------------- ledger


def ledger_path(tid, root=None):
    return Path(root or ROOT) / TICKETS_DIR / f"{tid}.md"


def render_ledger(tid, number, title, criteria, verify, out_of_scope, derived):
    cell = lambda s: s.replace("|", "\\|")  # noqa: E731
    rows = "\n".join(f"| {i} | {k} | {cell(t)} | | no |" for i, k, t in criteria)
    source = "derived from the issue's Done-when" if derived else "copied verbatim from the issue"
    oos = "\n".join(out_of_scope) if out_of_scope else "- (none listed)"
    return f"""# {tid} (#{number}) -- {title}
Status: in-dev
Round: 0 / {MAX_ROUNDS}
Red commit: (none yet)
Contract frozen: {dt.date.today().isoformat()}

## Acceptance criteria ({source}; never reword -- only the owner changes them)
| ID | Kind | Criterion | Check | Passes |
|----|------|-----------|-------|--------|
{rows}

## Verify
`{verify or "(none -- dev must add one before the red commit)"}`

## Out of scope
{oos}

## QA findings
| ID | Round | Kind | Cites | Reproduction | Status |
|----|-------|------|-------|--------------|--------|

## Dev log (newest first, 1-3 lines per session)
"""


def init(ref):
    number, tid = resolve(ref)
    path = ledger_path(tid)
    if path.exists():
        print(f"exists: {path.relative_to(ROOT)}")
        return 0
    issue = _gh_json(["issue", "view", str(number), "--json", "title,body"])
    body = issue["body"] or ""
    criteria, derived = parse_acceptance(body), False
    if not criteria:
        criteria, derived = parse_done_when(body), True
    if not criteria:
        raise SystemExit(f"ticket.py: #{number} has neither AC lines nor a Done-when; write them first")
    title = ID_RE.sub("", issue["title"]).strip()
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_ledger(tid, number, title, criteria, parse_verify(body), parse_out_of_scope(body), derived))
    print(f"created: {path.relative_to(ROOT)} ({len(criteria)} criteria{', derived' if derived else ''})")
    return 0


def show(ref):
    number, tid = resolve(ref)
    issue = _gh_json(["issue", "view", str(number), "--json", "number,title,state,labels,body,comments"])
    labels = ", ".join(l["name"] for l in issue["labels"])
    print(f"# #{issue['number']} {issue['title']}\nState: {issue['state']} | Labels: {labels}\n")
    print(issue["body"] or "(empty body)")
    for c in issue["comments"][-2:]:
        print(f"\n--- comment by {c['author']['login']} {c['createdAt'][:10]} ---\n{c['body']}")
    path = ledger_path(tid)
    print(f"\n===== LEDGER {TICKETS_DIR}/{tid}.md =====")
    print(path.read_text(encoding="utf-8") if path.exists() else "NO LEDGER YET (ticket.py init)")
    queue = _gh_json(["issue", "list", "--label", "status: ready-for-qa", "--limit", "200", "--json", "number"])
    print(f"\nready-for-qa queue: {len(queue)}")
    return 0


# ---------------------------------------------------------------- verify


def _shell_command(cmd):
    if os.name == "nt":  # cmd.exe reads "venv/Scripts/x" as venv + switch /Scripts
        cmd = cmd.replace("venv/Scripts/", "venv\\Scripts\\")
    return cmd


def run_verify(tid, root=ROOT, capture=False, timeout=VERIFY_TIMEOUT_S):
    path = ledger_path(tid, root)
    cmd = parse_verify(path.read_text(encoding="utf-8")) if path.exists() else None
    if not cmd or cmd.startswith("("):
        return None, f"{path.name}: no Verify command"
    try:
        p = subprocess.run(_shell_command(cmd), shell=True, cwd=root, capture_output=capture, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 1, f"Verify timed out after {timeout}s: {cmd}"
    out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
    return p.returncode, out


def verify(ref):
    _, tid = resolve(ref)
    rc, msg = run_verify(tid)
    if rc is None:
        print(msg)
        return 1
    return rc


# ---------------------------------------------------------------- Stop hook


def _marker_path(root):
    return Path(root) / STATE_DIR / MARKER


def _read_marker(root):
    try:
        return json.loads(_marker_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_marker(root, marker):
    path = _marker_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(marker), encoding="utf-8")


def dev_start(ref, root=ROOT):
    number, tid = resolve(ref)
    _write_marker(root, {"ticket": tid, "number": number, "started": dt.datetime.now().isoformat(),
                         "session": None, "blocks": 0})
    print(f"Stop hook armed for {tid}: a turn cannot end while its Verify is red.")
    return 0


def dev_stop(root=ROOT):
    _marker_path(root).unlink(missing_ok=True)
    print("Stop hook disarmed.")
    return 0


def tree_state(root):
    """Hash of HEAD plus every uncommitted change under the watched paths."""
    git = lambda *a: subprocess.run(["git", *a], cwd=root, capture_output=True).stdout  # noqa: E731
    h = hashlib.sha256(git("rev-parse", "HEAD"))
    h.update(git("diff", "HEAD", "--", *WATCHED_PATHS))
    for name in sorted(git("ls-files", "--others", "--exclude-standard", "--", *WATCHED_PATHS).split()):
        h.update(name)
        try:
            h.update((Path(root) / name.decode()).read_bytes())
        except OSError:
            pass
    return h.hexdigest()


def stop_hook_decision(payload, root=ROOT):
    """None to let the turn end, else the block reason."""
    if re.search(r"(?m)^\s*VERDICT:", payload.get("last_assistant_message") or ""):
        return None  # a QA turn: never push QA into fixing code
    marker = _read_marker(root)
    if not marker:
        return None
    try:
        age = dt.datetime.now() - dt.datetime.fromisoformat(marker["started"])
    except (KeyError, ValueError):
        return None
    if age > dt.timedelta(hours=MARKER_MAX_AGE_H):
        return None
    session = payload.get("session_id")
    if marker.get("session") is None and session:
        marker["session"] = session  # the first session to stop after dev-start owns the marker
    elif marker.get("session") and session and marker["session"] != session:
        return None
    if payload.get("stop_hook_active") and marker.get("blocks", 0) >= MAX_FORCED_CONTINUES:
        marker["blocks"] = 0
        _write_marker(root, marker)
        return None
    state = tree_state(root)
    cache = Path(root) / STATE_DIR / f"last-green-{marker['ticket']}"
    if cache.exists() and cache.read_text(encoding="utf-8") == state:
        _write_marker(root, marker)
        return None
    rc, out = run_verify(marker["ticket"], root, capture=True)
    if rc is None or rc == 0:
        if rc == 0:
            cache.write_text(state, encoding="utf-8")
        marker["blocks"] = 0
        _write_marker(root, marker)
        return None
    marker["blocks"] = marker.get("blocks", 0) + 1
    _write_marker(root, marker)
    tail = "\n".join(out.strip().splitlines()[-40:])
    return (
        f"{marker['ticket']}: Verify is red (forced continue {marker['blocks']}/{MAX_FORCED_CONTINUES}). "
        "Fix the code; do not edit or delete the red-commit acceptance tests. "
        "If the test itself is wrong, stop and say why.\nLast output:\n" + tail
    )


def stop_hook(root=ROOT):
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return 0
    reason = stop_hook_decision(payload, root)
    if reason:
        print(json.dumps({"decision": "block", "reason": reason}))
    return 0


# ---------------------------------------------------------------- commit-msg


def closing_keywords(message):
    lines = [l for l in message.splitlines() if not l.startswith("#")]
    return [m.group(0) for m in CLOSING_RE.finditer("\n".join(lines))]


def check_commit_msg(path):
    hits = closing_keywords(Path(path).read_text(encoding="utf-8", errors="replace"))
    if hits:
        sys.stderr.write(
            f"commit-msg: {', '.join(hits)} would auto-close the issue on merge. "
            "Only QA closes tickets (CLAUDE.md): use 'Refs #N'.\n"
        )
        return 1
    return 0


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not argv:
        print(__doc__)
        return 2
    cmd, args = argv[0], argv[1:]
    table = {
        "show": lambda: show(args[0]),
        "init": lambda: init(args[0]),
        "verify": lambda: verify(args[0]),
        "dev-start": lambda: dev_start(args[0]),
        "dev-stop": dev_stop,
        "stop-hook": stop_hook,
        "check-commit-msg": lambda: check_commit_msg(args[0]),
    }
    if cmd not in table:
        print(__doc__)
        return 2
    return table[cmd]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
