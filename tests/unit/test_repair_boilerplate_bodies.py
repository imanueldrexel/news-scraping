"""SYS-73 (#223): the pure parts of scripts/repair_boilerplate_bodies.py. What the write path does to
the three stores is tested against a real database and a real FAISS store in
tests/integration/test_repair_boilerplate_bodies_live.py."""
import importlib.util
import os
from datetime import datetime

import pytest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "scripts", "repair_boilerplate_bodies.py")


@pytest.fixture(scope="module")
def repair():
    spec = importlib.util.spec_from_file_location("repair_boilerplate_bodies_unit", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSelectTargets:
    def test_a_polluted_body_is_selected_with_its_cleaned_text(self, repair):
        body = "Kalimat satu.\n\nBaca juga: Judul Lain\n\nKalimat dua."
        assert repair.select_targets([(1, body)]) == [(1, "Kalimat satu.\n\nKalimat dua.")]

    def test_a_clean_body_is_not_selected(self, repair):
        assert repair.select_targets([(1, "Kalimat satu.\n\nKalimat dua.")]) == []

    def test_a_body_the_cleaner_would_empty_is_left_alone(self, repair):
        assert repair.select_targets([(1, "ADVERTISEMENT\n\nGULIR UNTUK LANJUT BACA")]) == []

    def test_an_empty_or_missing_body_is_not_selected(self, repair):
        assert repair.select_targets([(1, ""), (2, None)]) == []

    def test_prose_before_a_widget_is_kept(self, repair):
        prose = "Pemerintah menetapkan target pertumbuhan ekonomi tahun depan " + "kata " * 30
        assert repair.select_targets([(7, prose + "Tautan telah disalin energi hijau")]) == [(7, prose.strip())]

    def test_the_order_and_ids_are_kept(self, repair):
        rows = [(3, "Satu.\n\nADVERTISEMENT\n\nDua."), (1, "bersih"), (2, "Tiga.\n\nBaca juga: X\n\nEmpat.")]
        assert [sid for sid, _ in repair.select_targets(rows)] == [3, 2]

    def test_a_second_pass_selects_nothing(self, repair):
        once = repair.select_targets([(1, "A.\n\nBaca juga: X\n\nB.\n\nADVERTISEMENT\n\nC.")])
        assert repair.select_targets(once) == []


class TestParseUntil:
    def test_no_deadline(self, repair):
        assert repair.parse_until(None) is None and repair.parse_until("") is None

    def test_a_local_time_today(self, repair):
        now = datetime(2026, 10, 5, 8, 15, 42)
        assert repair.parse_until("11:30", now=now) == datetime(2026, 10, 5, 11, 30)

    def test_a_time_already_past_today_means_tomorrow(self, repair):
        """SYS-111 (#287): `--until 06:15` given at 20:04 is tomorrow morning, not this morning."""
        now = datetime(2026, 10, 8, 20, 4)
        assert repair.parse_until("06:15", now=now) == datetime(2026, 10, 9, 6, 15)

    def test_the_current_minute_is_tomorrow(self, repair):
        now = datetime(2026, 10, 8, 11, 30)
        assert repair.parse_until("11:30", now=now) == datetime(2026, 10, 9, 11, 30)


class TestTooClose:
    """SYS-111: a write path must not start deleting with less than MIN_RUN_MINUTES to run."""

    def test_no_deadline_is_never_too_close(self, repair):
        assert not repair.too_close(None)

    def test_inside_the_margin(self, repair):
        now = datetime(2026, 10, 8, 6, 1)
        assert repair.too_close(repair.parse_until("06:15", now=now), now=now)

    def test_at_the_margin_it_may_start(self, repair):
        now = datetime(2026, 10, 8, 6, 0)
        assert repair.MIN_RUN_MINUTES == 15
        assert not repair.too_close(repair.parse_until("06:15", now=now), now=now)

    def test_the_evening_run_that_lost_its_l2_may_start(self, repair):
        now = datetime(2026, 10, 8, 20, 4)
        assert not repair.too_close(repair.parse_until("06:15", now=now), now=now)
