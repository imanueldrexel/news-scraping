"""DBT-15 (#50): async route handlers ran blocking FAISS/Postgres/Gemini work
inline on the event loop, and the lazy singleton getters had no lock -- two
simultaneous first requests could each construct their own
ChunkFAISSDatasource (two embedding-model loads, two FAISS index loads).

api_query/api_query_form/api_stats now dispatch through run_in_threadpool
(same pattern OPS-14 already established for api_health), and _get_processor/
_get_stats_ds use double-checked locking around a shared threading.Lock.
"""
import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import newscrawler.web.app as app_mod


def _reset_singletons():
    app_mod._db_client = None
    app_mod._faiss_ds = None
    app_mod._processor = None
    app_mod._stats_ds = None


class TestQueryRoutesRunOffTheEventLoop:
    def setup_method(self):
        _reset_singletons()

    def teardown_method(self):
        _reset_singletons()

    def test_api_stats_payload_runs_on_a_worker_thread(self):
        seen = {}

        def fake_payload():
            seen["thread"] = threading.get_ident()
            return {"ok": True}

        with patch.object(app_mod, "_stats_payload", fake_payload):
            result = asyncio.run(app_mod.api_stats())

        assert result == {"ok": True}
        assert seen["thread"] != threading.get_ident()

    def test_run_query_helper_calls_get_processor_and_query(self):
        mock_processor = MagicMock()
        mock_processor.query.return_value = {"answer": "x"}
        with patch.object(app_mod, "_get_processor", return_value=mock_processor):
            result = app_mod._run_query(question="hi")

        assert result == {"answer": "x"}
        mock_processor.query.assert_called_once_with(question="hi")

    def test_run_query_executes_on_a_worker_thread_via_run_in_threadpool(self):
        from starlette.concurrency import run_in_threadpool

        seen = {}

        def fake_run_query(**kwargs):
            seen["thread"] = threading.get_ident()
            return {"answer": "ok", "session_id": None}

        with patch.object(app_mod, "_run_query", fake_run_query):
            asyncio.run(run_in_threadpool(app_mod._run_query, question="hi"))

        assert seen["thread"] != threading.get_ident()


class TestSingletonConstructionIsLockedAgainstConcurrentFirstRequests:
    def setup_method(self):
        _reset_singletons()

    def teardown_method(self):
        _reset_singletons()

    def test_get_processor_called_from_many_threads_constructs_faiss_datasource_once(self):
        construct_calls = []

        def slow_construct():
            construct_calls.append(1)
            time.sleep(0.05)  # widen the race window a real ~10s model load creates
            return MagicMock()

        with patch.object(app_mod, "SQLAlchemyClient", return_value=MagicMock()), \
             patch.object(app_mod, "ChunkFAISSDatasource", side_effect=slow_construct), \
             patch.object(app_mod, "QueryProcessor", return_value=MagicMock()):
            threads = [threading.Thread(target=app_mod._get_processor) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert len(construct_calls) == 1, "ChunkFAISSDatasource must be constructed exactly once"

    def test_get_stats_ds_called_from_many_threads_constructs_once(self):
        construct_calls = []

        def slow_construct(client):
            construct_calls.append(1)
            time.sleep(0.05)
            return MagicMock()

        with patch.object(app_mod, "SQLAlchemyClient", return_value=MagicMock()), \
             patch.object(app_mod, "SQLAlchemyNewsletterDataSource", side_effect=slow_construct):
            threads = [threading.Thread(target=app_mod._get_stats_ds) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert len(construct_calls) == 1

    def test_get_processor_returns_the_same_instance_on_every_call(self):
        with patch.object(app_mod, "SQLAlchemyClient", return_value=MagicMock()), \
             patch.object(app_mod, "ChunkFAISSDatasource", return_value=MagicMock()), \
             patch.object(app_mod, "QueryProcessor", return_value=MagicMock()) as mock_qp:
            first = app_mod._get_processor()
            second = app_mod._get_processor()

        assert first is second
        mock_qp.assert_called_once()
