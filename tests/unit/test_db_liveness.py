"""OPS-36 (#209): the DB liveness probe alerts once when the database stops
answering (after 2 failed probes), once when it recovers, never in between,
and never raises. The 2026-09-30 Docker stall accepted TCP and hung every
query, so the probe needs a client-side deadline."""
import importlib.util
import os
import sys
import threading
import types

import pytest

_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "scripts", "db_liveness.py")


def _load():
    spec = importlib.util.spec_from_file_location("db_liveness", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


live = _load()
UP = {"status": "up", "failures": 0, "since": None}


class TestStep:
    def test_one_failure_is_not_an_alert(self):
        state, alert = live.step(UP, False, "timeout", "t1")
        assert alert is None and state["failures"] == 1 and state["status"] == "up"

    def test_the_second_failure_in_a_row_alerts_down_once(self):
        state, _ = live.step(UP, False, "timeout", "t1")
        state, alert = live.step(state, False, "timeout", "t2")
        assert alert and "DOWN since t1" in alert and state["status"] == "down"
        state, again = live.step(state, False, "timeout", "t3")
        assert again is None, "no repeat while down"

    def test_recovery_after_a_down_alert_is_announced_once(self):
        down = {"status": "down", "failures": 3, "since": "t1"}
        state, alert = live.step(down, True, None, "t9")
        assert alert and "recovered" in alert and "down since t1" in alert
        assert live.step(state, True, None, "t10")[1] is None

    def test_a_blip_that_never_alerted_recovers_silently(self):
        state, _ = live.step(UP, False, "timeout", "t1")
        state, alert = live.step(state, True, None, "t2")
        assert alert is None and state == UP


class TestProbe:
    def test_a_hung_query_is_down_within_the_deadline(self, monkeypatch):
        gate = threading.Event()
        monkeypatch.setattr(live, "_select_one", lambda result: gate.wait(5))
        ok, reason = live.probe(deadline_s=0.2)
        gate.set()
        assert not ok and "no answer to SELECT 1 within" in reason

    def test_an_error_is_down_with_its_reason(self, monkeypatch):
        monkeypatch.setattr(live, "_select_one", lambda result: result.update(error="OperationalError: refused"))
        assert live.probe(deadline_s=1) == (False, "OperationalError: refused")

    def test_a_good_answer_is_up(self, monkeypatch):
        monkeypatch.setattr(live, "_select_one", lambda result: result.update(ok=True))
        assert live.probe(deadline_s=1) == (True, None)


class TestMain:
    @pytest.fixture
    def env(self, monkeypatch, tmp_path):
        sent = []
        monkeypatch.setattr(live, "STATE_PATH", str(tmp_path / "state.json"))
        monkeypatch.setitem(sys.modules, "notify_telegram", types.SimpleNamespace(send=sent.append))
        return sent

    def test_down_down_up_sends_exactly_two_alerts(self, env, monkeypatch):
        answers = iter([(False, "hung"), (False, "hung"), (False, "hung"), (True, None)])
        monkeypatch.setattr(live, "probe", lambda: next(answers))
        assert [live.main([]) for _ in range(4)] == [1, 1, 1, 0]
        assert len(env) == 2 and "DOWN" in env[0] and "recovered" in env[1]

    def test_a_failing_send_never_raises(self, env, monkeypatch):
        def broken(msg):
            raise RuntimeError("telegram down")
        monkeypatch.setitem(sys.modules, "notify_telegram", types.SimpleNamespace(send=broken))
        monkeypatch.setattr(live, "probe", lambda: (False, "hung"))
        live.main([])
        assert live.main([]) == 1

    def test_check_mode_writes_no_state(self, env, monkeypatch, tmp_path):
        monkeypatch.setattr(live, "probe", lambda: (False, "hung"))
        assert live.main(["--check"]) == 1
        assert not os.path.exists(live.STATE_PATH) and env == []
