"""DBT-49 (#203): a retrain with no --encoder must use the encoder production
runs (the committed sidecar's), never silently a different default."""
import importlib.util
import json
import os
import sys

_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "scripts", "train_importance_probe.py")


def _load():
    spec = importlib.util.spec_from_file_location("train_importance_probe_dbt49", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved, sys.argv = sys.argv, ["train_importance_probe.py"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


tp = _load()


def _sidecar(tmp_path, model):
    with open(tmp_path / tp.PROBE_SIDECAR, "w", encoding="utf-8") as f:
        json.dump({"embedding_model": model}, f)


def test_no_flag_resolves_to_the_committed_encoder(tmp_path):
    _sidecar(tmp_path, "intfloat/multilingual-e5-large")
    assert tp.resolve_encoder(None, str(tmp_path)) == "intfloat/multilingual-e5-large"


def test_the_real_committed_artifact_is_what_a_plain_retrain_uses():
    assert tp.resolve_encoder(None, tp.PROBE_DIR) == tp.committed_encoder(tp.PROBE_DIR) is not None


def test_a_different_encoder_is_allowed_loudly(tmp_path, caplog):
    _sidecar(tmp_path, "intfloat/multilingual-e5-large")
    with caplog.at_level("WARNING"):
        assert tp.resolve_encoder("intfloat/multilingual-e5-base", str(tmp_path)) == "intfloat/multilingual-e5-base"
    assert any("CHANGES the encoder production embeds with" in r.getMessage() for r in caplog.records)


def test_without_an_artifact_the_design_default_applies(tmp_path):
    assert tp.resolve_encoder(None, str(tmp_path)) == tp.DEFAULT_PROBE_ENCODER
