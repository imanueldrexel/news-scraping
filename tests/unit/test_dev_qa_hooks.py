"""OPS-50: the deterministic half of the dev/QA contract (scripts/ticket.py).

Parsing an issue into a ledger, the Stop hook that keeps a dev turn going while
the ticket's Verify is red, and the commit-msg check against auto-closing.
"""
import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("ticket", ROOT / "scripts" / "ticket.py")
ticket = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ticket)

PY = f'"{sys.executable}"'
RED = f'{PY} -c "print(\'boom at line 7\'); raise SystemExit(1)"'
GREEN = f'{PY} -c "raise SystemExit(0)"'

NEW_FORM = """## Goal
Refuse the MK shape.

## Acceptance criteria
- AC1 [unit]: Given the MK sentence, when parsed, then it is refused.
- AC2 [live: SELECT count(*) FROM nli_shadow]: Given the 12:00 run, then the count rises.

## Verify
`venv\\Scripts\\python.exe -m pytest tests/unit/test_sys152_acceptance.py -q`

## Out of scope
- the NLI judge
"""

LEGACY = """## Proposal
stuff

## Done when
- [ ] Unit tests on the six sentences:
  - **MK refused**;
  - **PHK kept**;
- [ ] a fabricated `kutipan` is refused
- [x] `tests/unit` green
"""


def test_parse_acceptance_reads_ids_kinds_and_text():
    assert ticket.parse_acceptance(NEW_FORM) == [
        ("AC1", "unit", "Given the MK sentence, when parsed, then it is refused."),
        ("AC2", "live: SELECT count(*) FROM nli_shadow", "Given the 12:00 run, then the count rises."),
    ]
    assert ticket.parse_verify(NEW_FORM).endswith("test_sys152_acceptance.py -q")
    assert ticket.parse_out_of_scope(NEW_FORM) == ["- the NLI judge"]


def test_indented_lines_continue_the_ac_above_until_a_blank_line():
    body = "- AC1 [unit]: Given x, then:\n  - a holds;\n  - b holds.\n\n  stray indented text\n- AC2: y\n"
    assert ticket.parse_acceptance(body) == [
        ("AC1", "unit", "Given x, then: a holds; b holds."),
        ("AC2", "?", "y"),
    ]


def test_init_writes_the_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(ticket, "ROOT", tmp_path)
    monkeypatch.setattr(ticket, "resolve", lambda ref: (9, "SYS-9"))
    monkeypatch.setattr(ticket, "_gh_json", lambda args: {"title": "[SYS-9] t", "body": NEW_FORM})
    assert ticket.init("SYS-9") == 0
    text = (tmp_path / "tickets" / "SYS-9.md").read_bytes().decode("utf-8")
    assert "\r\n" not in text and "| AC1 | unit |" in text
    assert ticket.parse_verify(text).endswith("test_sys152_acceptance.py -q")


def test_legacy_done_when_items_become_criteria_with_nested_lines_joined():
    crit = ticket.parse_done_when(LEGACY)
    assert [c[0] for c in crit] == ["AC1", "AC2", "AC3"]
    assert crit[0][2] == "Unit tests on the six sentences:; **MK refused**;; **PHK kept**;"
    assert crit[2] == ("AC3", "?", "`tests/unit` green")
    assert ticket.parse_acceptance(LEGACY) == []


def test_bug_template_inline_done_when_field():
    body = "- **Fix:** x\n- **Done when:** the health line is OK\n"
    assert ticket.parse_done_when(body) == [("AC1", "?", "the health line is OK")]


def test_ledger_round_trips_verify_and_escapes_pipes():
    text = ticket.render_ledger("SYS-1", 2, "t", [("AC1", "unit", "a | b")], "pytest -q", [], False)
    assert ticket.parse_verify(text) == "pytest -q"
    assert "a \\| b" in text
    assert "Round: 0 / 3" in text


@pytest.mark.parametrize(
    "msg", ["x\n\nFixes #12", "closes #12", "Resolved: imanueldrexel/news-scraping#5", "fixed #3"]
)
def test_closing_keywords_are_rejected(msg, tmp_path):
    f = tmp_path / "MSG"
    f.write_text(msg, encoding="utf-8")
    assert ticket.check_commit_msg(f) == 1


@pytest.mark.parametrize(
    "msg",
    ["fix(crawler): [SYS-01] x\n\nRefs #12", "state(qa): 6 defects closed, #458-#461 filed", "# Fixes #9 (comment)"],
)
def test_refs_and_prose_are_accepted(msg, tmp_path):
    f = tmp_path / "MSG"
    f.write_text(msg, encoding="utf-8")
    assert ticket.check_commit_msg(f) == 0


# ---------------------------------------------------------------- Stop hook


@pytest.fixture
def repo(tmp_path):
    git = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)  # noqa: E731
    git("init", "-q")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("x = 1\n")
    git("add", ".")
    git("-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "init")
    return tmp_path


def _arm(root, verify, session=None, blocks=0, started=None):
    ledger = ticket.ledger_path("T-1", root)
    ledger.parent.mkdir(exist_ok=True)
    ledger.write_text(ticket.render_ledger("T-1", 1, "t", [("AC1", "unit", "c")], verify, [], False))
    ticket._write_marker(root, {"ticket": "T-1", "number": 1, "session": session, "blocks": blocks,
                                "started": (started or dt.datetime.now()).isoformat()})


def test_no_marker_never_blocks(repo):
    assert ticket.stop_hook_decision({"session_id": "s"}, repo) is None


def test_red_verify_blocks_with_output_tail(repo):
    _arm(repo, RED)
    reason = ticket.stop_hook_decision({"session_id": "s"}, repo)
    assert "Verify is red" in reason and "boom at line 7" in reason
    marker = ticket._read_marker(repo)
    assert marker["session"] == "s" and marker["blocks"] == 1


def test_qa_turn_with_verdict_is_never_blocked(repo):
    _arm(repo, RED)
    assert ticket.stop_hook_decision({"session_id": "s", "last_assistant_message": "x\nVERDICT: BLOCKED (1)"},
                                     repo) is None


def test_another_session_is_not_blocked(repo):
    _arm(repo, RED, session="dev")
    assert ticket.stop_hook_decision({"session_id": "qa"}, repo) is None


def test_forced_continues_are_capped(repo):
    _arm(repo, RED, session="s", blocks=ticket.MAX_FORCED_CONTINUES)
    assert ticket.stop_hook_decision({"session_id": "s", "stop_hook_active": True}, repo) is None
    assert ticket._read_marker(repo)["blocks"] == 0


def test_stale_marker_is_ignored(repo):
    _arm(repo, RED, started=dt.datetime.now() - dt.timedelta(hours=ticket.MARKER_MAX_AGE_H + 1))
    assert ticket.stop_hook_decision({"session_id": "s"}, repo) is None


def test_green_is_cached_until_the_watched_tree_changes(repo):
    _arm(repo, GREEN)
    assert ticket.stop_hook_decision({"session_id": "s"}, repo) is None
    _arm(repo, RED, session="s")  # ledger is not a watched path: the cached green holds
    assert ticket.stop_hook_decision({"session_id": "s"}, repo) is None
    (repo / "tests" / "test_x.py").write_text("x = 2\n")
    assert "Verify is red" in ticket.stop_hook_decision({"session_id": "s"}, repo)


def test_stop_hook_prints_block_json(repo, monkeypatch, capsys):
    _arm(repo, RED)
    monkeypatch.setattr(sys, "stdin", type("S", (), {"read": lambda self: json.dumps({"session_id": "s"})})())
    assert ticket.stop_hook(repo) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "block"


# ---------------------------------------------------------------- wiring


def test_project_settings_register_the_stop_hook():
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [h["command"] for entry in settings["hooks"]["Stop"] for h in entry["hooks"]]
    assert any("scripts/ticket.py" in c and "stop-hook" in c for c in commands)


def test_commit_msg_hook_calls_the_check():
    hook = (ROOT / ".githooks" / "commit-msg").read_text(encoding="utf-8")
    assert "ticket.py" in hook and "check-commit-msg" in hook


def test_qa_rules_verdicts_match_the_hook():
    rules = (ROOT / ".claude" / "qa-rules.md").read_text(encoding="utf-8")
    for verdict in ("VERDICT: PASS", "VERDICT: HELD", "VERDICT: BLOCKED", "VERDICT: NEEDS-DECISION"):
        assert verdict in rules
