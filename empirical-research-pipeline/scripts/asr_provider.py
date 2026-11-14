# -*- coding: utf-8 -*-
"""Speech transcription with real time alignment.

Like OCR, a transcript is *not* a fact: each segment is a ``source_unit`` with
``status='partial'``, word-level timings and confidence, an explicit
``unrecovered`` note, and a receipt naming the engine and model.  A value that
comes from speech must be re-listened to at the recorded time range before it is
used (``replay`` gives the exact interval; ``adjudicate`` records the re-listen).

Providers:

* ``vosk``  - offline Kaldi models (``pip install vosk`` + a model directory).
* none      - reported honestly as ``engine_missing``; no empty success.

CLI::

    python asr_provider.py --root . providers
    python asr_provider.py --root . transcribe --unit <media_unit> \\
        [--model path/to/vosk-model] [--lang en]
    python asr_provider.py --root . replay --unit <segment_unit> --out clip.wav
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from typing import Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract_v2 as C
import source_units as SU

DEFAULT_MODEL_ENV = "VOSK_MODEL"
MODEL_SEARCH = ("models/vosk-model-small-en-us-0.15",
                "../models/vosk-model-small-en-us-0.15")


def _producer(**kw) -> dict:
    return C.producer_for("asr_provider", version="2.0", module_file=__file__,
                          **kw)


class AsrUnavailable(RuntimeError):
    pass


class AsrProvider:
    name = "base"
    version = "0"

    def available(self) -> bool:
        raise NotImplementedError

    def reason(self) -> str:
        return "not available"

    def transcribe(self, wav_path: str, *, lang: str | None = None) -> list[dict]:
        """Return ``[{start,end,text,words:[{word,start,end,conf}]}]`` (seconds)."""
        raise NotImplementedError


class VoskProvider(AsrProvider):
    name = "vosk"

    def __init__(self, model_path: str | None = None):
        self.model_path = model_path or os.environ.get(DEFAULT_MODEL_ENV, "")
        self.version = "?"

    def available(self) -> bool:
        try:
            import vosk  # noqa: F401
        except Exception:
            return False
        return bool(self.model_path) and Path(self.model_path).is_dir()

    def reason(self) -> str:
        try:
            import vosk  # noqa: F401
        except Exception:
            return "vosk is not installed (pip install vosk)"
        if not self.model_path:
            return (f"no model directory (set {DEFAULT_MODEL_ENV} or --model to "
                    f"an unzipped vosk model)")
        if not Path(self.model_path).is_dir():
            return f"model directory {self.model_path!r} does not exist"
        return "ok"

    def transcribe(self, wav_path: str, *, lang: str | None = None) -> list[dict]:
        from vosk import KaldiRecognizer, Model, SetLogLevel
        import vosk as vosk_pkg
        SetLogLevel(-1)
        self.version = getattr(vosk_pkg, "__version__", "?")
        model = Model(self.model_path)
        with wave.open(wav_path, "rb") as wf:
            rate = wf.getframerate()
            rec = KaldiRecognizer(model, rate)
            rec.SetWords(True)
            words: list[dict] = []
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                if rec.AcceptWaveform(data):
                    words.extend(json.loads(rec.Result()).get("result", []))
            words.extend(json.loads(rec.FinalResult()).get("result", []))
        return _words_to_segments(words)


def _words_to_segments(words: list[dict], *, gap: float = 0.35,
                       max_len: float = 15.0) -> list[dict]:
    segments: list[dict] = []
    current: list[dict] = []

    def flush() -> None:
        if not current:
            return
        segments.append({
            "start": round(current[0]["start"], 3),
            "end": round(current[-1]["end"], 3),
            "text": " ".join(w["word"] for w in current),
            "words": [{"word": w["word"], "start": round(w["start"], 3),
                       "end": round(w["end"], 3),
                       "conf": round(float(w.get("conf", 0.0)), 4)}
                      for w in current],
            "conf": round(sum(float(w.get("conf", 0.0)) for w in current) /
                          len(current), 4),
        })
        current.clear()

    for word in words:
        if current:
            if word["start"] - current[-1]["end"] >= gap or \
                    word["end"] - current[0]["start"] > max_len:
                flush()
        current.append(word)
    flush()
    return segments


def find_model(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    env = os.environ.get(DEFAULT_MODEL_ENV)
    if env:
        return env
    for rel in MODEL_SEARCH:
        cand = Path(__file__).resolve().parent.parent / rel
        if cand.is_dir():
            return str(cand)
    return None


def providers(model: str | None = None) -> dict[str, AsrProvider]:
    return {"vosk": VoskProvider(find_model(model))}


def extract_audio(media_path: str, out_wav: str) -> str:
    """Convert any ffmpeg-readable media to 16 kHz mono 16-bit wav."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AsrUnavailable("ffmpeg is not on PATH; cannot extract audio")
    Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", media_path,
           "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", out_wav]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0 or not Path(out_wav).is_file():
        raise AsrUnavailable(f"ffmpeg failed: {proc.stderr[:400]}")
    return out_wav


def transcribe_media(project: C.Project, units: SU.SourceUnits,
                     media_unit: Mapping, *, provider: AsrProvider | None = None,
                     lang: str | None = None) -> dict:
    data = media_unit["data"]
    src = Path(data["source"])
    path = src if src.is_absolute() else (project.root / src)
    if not path.is_file():
        path = project.root / "materials" / data["source"]
    try:
        prov = provider or providers()["vosk"]
        if not prov.available():
            raise AsrUnavailable(prov.reason())
    except AsrUnavailable as exc:
        receipt = units.receipt(data["source"], data["source_sha256"], [{
            "step": "asr", "engine": "none", "outcome": str(exc)}], "failed",
            failure_class="engine_missing",
            notes="media remains pending; transcribed speech is not a fact")
        project.append("recovery_receipt", receipt, enforce_transition=False)
        return {"provider": None, "segments": [], "status": "failed",
                "reason": str(exc), "receipt": receipt["id"]}
    wav = project.path("media", f"{media_unit['id']}.wav")
    try:
        extract_audio(str(path), str(wav))
        segments = prov.transcribe(str(wav), lang=lang)
    except Exception as exc:                            # noqa: BLE001
        receipt = units.receipt(data["source"], data["source_sha256"], [{
            "step": "asr", "engine": prov.name,
            "outcome": f"{type(exc).__name__}: {exc}"}], "failed",
            failure_class="other")
        project.append("recovery_receipt", receipt, enforce_transition=False)
        return {"provider": prov.name, "segments": [], "status": "failed",
                "reason": str(exc), "receipt": receipt["id"]}
    out: list[dict] = []
    for i, seg in enumerate(segments):
        locator = {"type": "media_segment", "start": seg["start"],
                   "end": seg["end"], "index": i}
        seg_sha = hashlib.sha256(C.canonical_json(seg).encode()).hexdigest()
        payload = {
            "source": data["source"], "source_sha256": data["source_sha256"],
            "unit_type": "segment", "parent_source": data["source"],
            "locator": locator,
            "representation": data["representation"],
            "representation_sha256": seg_sha,
            "engine": {"name": prov.name, "version": prov.version,
                       "params": {"model": prov.model_path, "lang": lang,
                                  "wav": wav.relative_to(
                                      project.root).as_posix()}},
            "recovered_scope": {"transcript": seg["text"],
                                "words": seg["words"],
                                "mean_conf": seg["conf"],
                                "low_confidence_words": [
                                    w["word"] for w in seg["words"]
                                    if w["conf"] < 0.7],
                                "speaker": None},
            "unrecovered": ["speaker identity unresolved",
                            "ASR transcription is not a verified reading: the "
                            "recorded time range must be re-listened to before "
                            "a spoken value is used as a fact"],
            "notes": "asr",
        }
        rec, _ = units.upsert(payload, status="partial")
        out.append({"unit": rec["id"], "start": seg["start"], "end": seg["end"],
                    "text": seg["text"], "words": seg["words"]})
    receipt = units.receipt(
        data["source"], data["source_sha256"],
        [{"step": "asr", "engine": prov.name, "version": prov.version,
          "model": prov.model_path, "segments": len(out), "lang": lang}],
        "recovered", notes=f"{len(out)} segment(s) transcribed; still requires "
                           f"a re-listen of the original audio")
    project.append("recovery_receipt", receipt, enforce_transition=False)
    return {"provider": prov.name, "segments": out, "status": "partial",
            "receipt": receipt["id"]}


def replay(project: C.Project, segment_unit: Mapping, out_path: str) -> dict:
    """Cut the exact audio interval so it can actually be re-listened to."""
    data = segment_unit["data"]
    start, end = data["locator"]["start"], data["locator"]["end"]
    media = Path(data["source"])
    path = media if media.is_absolute() else project.root / media
    if not path.is_file():
        path = project.root / "materials" / data["source"]
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AsrUnavailable("ffmpeg is not on PATH; cannot cut the segment")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(path),
           "-ss", f"{start}", "-to", f"{end}", "-ac", "1", "-ar", "16000",
           str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not Path(out_path).is_file():
        raise AsrUnavailable(f"ffmpeg failed: {proc.stderr[:400]}")
    with wave.open(out_path, "rb") as wf:
        duration = wf.getnframes() / float(wf.getframerate())
    return {"segment": segment_unit["id"], "start": start, "end": end,
            "clip": out_path, "duration": round(duration, 3),
            "requested_duration": round(end - start, 3)}


def adjudicate(project: C.Project, units: SU.SourceUnits, segment_unit: Mapping,
               corrected_text: str, *, reviewer: str, note: str,
               speaker: str | None = None, supports: bool = True) -> dict:
    if not reviewer or not note:
        raise ValueError("a re-listen needs an actual reviewer and a note")
    data = dict(segment_unit["data"])
    scope = dict(data["recovered_scope"])
    scope["asr_transcript"] = scope.get("transcript")
    scope["transcript"] = corrected_text
    scope["reread_by"] = reviewer
    scope["reread_note"] = note
    if speaker:
        scope["speaker"] = speaker
    data["recovered_scope"] = scope
    data["engine"] = {"name": "human-relisten", "version": "1",
                      "params": {"reviewer": reviewer,
                                 "interval": data["locator"]}}
    data["unrecovered"] = [] if supports else [
        "re-listen contradicts the transcription"]
    rec = C.make_record("source_unit", segment_unit["id"], data,
                        producer=_producer(), status="recovered",
                        revision=segment_unit["revision"] + 1)
    project.append("source_unit", rec)
    event = C.make_record("review_event",
                          f"asr-relisten:{segment_unit['id']}:r{rec['revision']}",
                          {"dataset": "<source-unit>", "key": [segment_unit["id"]],
                           "target_type": "source_unit", "source_sha256": data["source_sha256"],
                           "unit_revision": rec["revision"], "unit_signature": C.signature(rec),
                           "column": "transcript",
                           "value_under_review": str(
                               scope.get("asr_transcript")),
                           "record_sha256": C.signature(segment_unit),
                           "method": "source_reread", "reviewer": reviewer,
                           "independence": "independent_of_asr",
                           "reread_scope": {"source": data["source"],
                                            "interval": data["locator"]},
                           "second_pass": {"transcript": corrected_text,
                                           "speaker": scope.get("speaker")},
                           "outcome": "corrected"
                           if scope.get("asr_transcript") != corrected_text
                           else "confirmed",
                           "checked_at": C._now(), "reason": note},
                          producer=_producer(), status="recorded")
    project.append("review_event", event, enforce_transition=False)
    return {"unit": rec["id"], "revision": rec["revision"], "event": event["id"]}


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="ASR providers")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("providers")
    p_tr = sub.add_parser("transcribe")
    p_tr.add_argument("--unit", required=True)
    p_tr.add_argument("--model")
    p_tr.add_argument("--lang")
    p_rep = sub.add_parser("replay")
    p_rep.add_argument("--unit", required=True)
    p_rep.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    units = SU.SourceUnits(proj, root=Path(args.root))
    if args.cmd == "providers":
        for name, prov in providers(getattr(args, "model", None)).items():
            print(f"{name:8s} available={prov.available()} {prov.reason()}")
        return 0
    unit = proj.latest("source_unit", args.unit)
    if unit is None:
        print(f"unknown unit {args.unit}", file=sys.stderr)
        return 2
    if args.cmd == "transcribe":
        res = transcribe_media(proj, units, unit,
                               provider=providers(args.model)["vosk"],
                               lang=args.lang)
        print(json.dumps({k: v for k, v in res.items() if k != "segments"},
                         ensure_ascii=False, indent=1))
        for seg in res["segments"]:
            print(f"  [{seg['start']:.2f}-{seg['end']:.2f}] {seg['text']}")
        return 0 if res["status"] != "failed" else 2
    if args.cmd == "replay":
        print(json.dumps(replay(proj, unit, args.out), ensure_ascii=False,
                         indent=1))
        return 0
    return 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
