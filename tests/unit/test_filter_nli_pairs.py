"""SYS-197 (#427, ADR-027): type misfits go to the `other` bucket with their label kept; the rules match the hand
check's misfits (real rows) and leave real denials and cause edits alone."""
import importlib.util
import json
import os

import pytest

_HERE = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "experiments")
_spec = importlib.util.spec_from_file_location("filter_nli_pairs", os.path.join(_HERE, "filter_nli_pairs.py"))
fl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fl)
_gspec = importlib.util.spec_from_file_location("gen_nli_pairs", os.path.join(_HERE, "gen_nli_pairs.py"))
gen = importlib.util.module_from_spec(_gspec)
_gspec.loader.exec_module(gen)


def pair(error_type, premise, hypothesis, kind="corrupted", label="unfaithful", pid="x-0"):
    return {"id": pid, "error_type": error_type, "premise": premise, "hypothesis": hypothesis, "kind": kind,
            "label": label}


@pytest.mark.parametrize("premise", [
    # hand-check misfits: a judgement, an adverb, a noun -- no one denies anything
    "Daryono menegaskan, kebiasaan melabeli daerah yang dilanda gempa merupakan pandangan keliru yang perlu dihentikan.",
    "Perbuatan tersebut meliputi penawaran jasa secara tidak benar, serta kekerasan yang dilakukan secara berlanjut.",
    "Teori konspirasi telah dikaitkan dengan prasangka dan penyangkalan perubahan iklim.",
])
def test_a_denial_seed_without_an_act_of_denying_is_a_misfit(premise):
    p = pair("denial", premise, "whatever", kind="restatement", label="faithful")    # every pair of the seed
    assert fl.misfit(p) == "denial-no-act"
    assert not gen.DENIAL_ACT.search(premise)


@pytest.mark.parametrize("premise", [
    "Kemenkeu membantah kabar bahwa PPN transfer bank naik.",
    "Kabar itu ditepis oleh juru bicara maskapai.",
    "Informasi yang beredar di media sosial itu tidak benar, kata Kominfo.",
    "Polisi menyebut video tersebut hoaks.",
])
def test_a_real_denial_stays(premise):
    assert fl.misfit(pair("denial", premise, "whatever")) is None


@pytest.mark.parametrize("premise,hypothesis", [
    # hand-check misfits: the edit is in the result, or inside a purpose clause
    ("David Chen kehilangan US$650 juta sehingga kekayaannya turun dari US$2 miliar menjadi US$1,35 miliar.",
     "David Chen kehilangan US$650 juta sehingga kekayaannya naik dari US$2 miliar menjadi US$1,35 miliar."),
    ("Pemerintah pun mendorong langkah pencegahan agar titik panas tidak berkembang menjadi kebakaran.",
     "Pemerintah pun mendorong langkah pencegahan agar hujan tidak berkembang menjadi kebakaran."),
    ("Harga cabai naik karena pasokan dari Jawa Tengah seret.",
     "Harga bawang naik karena pasokan dari Jawa Tengah seret."),                    # backward: effect before
])
def test_a_cause_edit_on_the_effect_side_is_a_misfit(premise, hypothesis):
    assert fl.misfit(pair("cause", premise, hypothesis)) == "cause-effect-side"


@pytest.mark.parametrize("premise,hypothesis", [
    ("Harga cabai naik karena pasokan dari Jawa Tengah seret.",
     "Harga cabai naik karena cuaca buruk di Jawa Tengah."),                        # the cause replaced
    ("Pasokan dari Jawa Tengah seret sehingga harga cabai naik.",
     "Permintaan dari Jakarta melonjak sehingga harga cabai naik."),                # forward: cause before
    ("Pasokan seret sehingga harga cabai naik.",
     "Pasokan seret sehingga harga cabai naik karena ulah spekulan."),               # a link added after the effect
    ("Kami berharap inisiatif ini meningkatkan kualitas hidup masyarakat, ujar Rozy.",
     "Kami berharap inisiatif ini meningkatkan kualitas hidup masyarakat, ujar Rozy karena tekanan pemerintah."),
    ("Suahasil juga mendorong agar pengumpulan iuran BPJS Kesehatan dapat ditingkatkan.",
     "Suahasil juga mendorong agar pengumpulan iuran BPJS Kesehatan dapat ditingkatkan agar defisit tertutup."),
    ("Kami tidak bertanggung jawab atas kerugian, sehingga kerugian yang timbul dari keputusan tersebut ditanggung.",
     "Kami tidak bertanggung jawab atas kerugian, sehingga kerugian yang timbul dari kesalahan redaksi ditanggung."),
    # a stray byte before the sentence is no edit; the real one is on the cause side
    ("�Warga tidak menerima bansos gara-gara tidak masuk data, ucap Andi.",
     "Warga tidak menerima bansos gara-gara tidak punya KTP, ucap Andi."),
    # the edit's clause holds no link: nothing says which side it is on
    ("Serangan kapal mendorong kenaikan harga minyak, meski rencana pelepasan cadangan menjadi faktor penahan.",
     "Serangan kapal mendorong kenaikan harga minyak, meski rencana kenaikan suku bunga menjadi faktor penahan."),
])
def test_a_cause_edit_stays(premise, hypothesis):
    assert fl.misfit(pair("cause", premise, hypothesis)) is None


def test_only_corrupted_cause_pairs_are_judged_by_edit_place():
    p = pair("cause", "Pasokan seret sehingga harga naik.", "Pasokan seret sehingga harga meningkat.",
             kind="restatement", label="faithful")
    assert fl.misfit(p) is None
    assert fl.misfit({**p, "kind": "corrupted", "label": "unfaithful"}) == "cause-effect-side"


def test_bucket_keeps_the_label_and_the_declared_type():
    rows = fl.bucket([pair("denial", "Itu pandangan keliru.", "Itu bukan pandangan keliru.", pid="d-0"),
                      pair("denial", "Kemenkeu membantah kabar itu.", "Kemenkeu membenarkan kabar itu.", pid="d-1")])
    assert [(r["error_type"], r["declared_type"], r["misfit"], r["label"]) for r in rows] == [
        ("other", "denial", "denial-no-act", "unfaithful"), ("denial", "denial", None, "unfaithful")]


def test_check_counts_hits_against_the_hand_check():
    pairs = [pair("denial", "Itu pandangan keliru.", "h", pid="a"), pair("denial", "Ini juga keliru.", "h", pid="b"),
             pair("denial", "Kemenkeu membantah.", "h", pid="c"), pair("hedge", "Diduga A.", "A.", pid="d")]
    final = [{"id": "a", "type_ok": "n"}, {"id": "b", "type_ok": "y"}, {"id": "c", "type_ok": "y"},
             {"id": "d", "type_ok": "n"}]
    report = fl.check(pairs, final)
    assert (report["denial-no-act"]["misfit"], report["denial-no-act"]["fit"]) == (1, ["b"])
    assert report["missed"] == ["d"]


def test_the_generator_seeds_denials_only_with_an_act_of_denying():
    denial = gen.cue_check("denial")
    assert denial("Kemenkeu membantah kabar bahwa PPN naik.")
    assert not denial("Kebiasaan itu merupakan pandangan keliru yang perlu dihentikan.")
    assert not denial("Penawaran jasa secara tidak benar dilarang.")


def test_main_writes_lf_jsonl(tmp_path):
    src, out = tmp_path / "raw.jsonl", tmp_path / "pairs.jsonl"
    src.write_text(json.dumps(pair("denial", "Itu keliru.", "h")) + "\n", encoding="utf-8")
    assert fl.main(["--pairs", str(src), "--out", str(out)]) == 0
    data = out.read_bytes()
    assert b"\r\n" not in data and json.loads(data)["error_type"] == "other"
