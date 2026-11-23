"""The `mat` command line. Exit codes: 0 ok, 1 runtime error, 2 usage error."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from mat import bom
from mat.core import midi
from mat.core.note_events import dump, schema_text
from mat.eval.suite import format_report, run_mono
from mat.synth.generate import build_clip, write_clip
from mat.synth.recipe import Recipe
from mat.synth.render import fetch_soundfont
from mat.transcribe.audio_io import AudioDecodeError
from mat.transcribe.pyin import transcribe_file


def _emit(obj: Any, as_json: bool, text: str) -> None:
    print(json.dumps(obj, indent=2) if as_json else text)


def cmd_transcribe(a: argparse.Namespace) -> int:
    src = Path(a.file)
    try:
        events = transcribe_file(src, a.instrument)
    except AudioDecodeError as e:
        _emit({"error": {"code": "decode_failed", "message": str(e)}}, a.json, f"error: {e}")
        return 1
    out = Path(a.out) if a.out else src.parent
    out.mkdir(parents=True, exist_ok=True)
    notes_path, midi_path = out / f"{src.stem}.notes.json", out / f"{src.stem}.mid"
    notes_path.write_text(dump(events))
    midi.write_midi(events, midi_path)
    summary = {
        "notes": len(events.notes),
        "warnings": [w.code for w in events.warnings],
        "notes_json": str(notes_path),
        "midi": str(midi_path),
    }
    _emit(summary, a.json, f"{len(events.notes)} notes -> {notes_path}, {midi_path}")
    for w in events.warnings:
        print(f"warning: {w.code}: {w.message}", file=sys.stderr)
    return 0


def cmd_synth_generate(a: argparse.Namespace) -> int:
    recipe = Recipe.load(Path(a.recipe))
    paths = write_clip(build_clip(recipe), Path(a.out), a.name)
    _emit({k: str(v) for k, v in paths.items()}, a.json, "\n".join(str(p) for p in paths.values()))
    return 0


def cmd_fetch_soundfont(a: argparse.Namespace) -> int:
    path = fetch_soundfont()
    _emit({"soundfont": str(path)}, a.json, str(path))
    return 0


def cmd_eval(a: argparse.Namespace) -> int:
    real = Path(a.real_dir) if a.real_dir else None
    report = run_mono(a.renderer, a.n, a.seed, real)
    _emit(report.to_dict(), a.json, format_report(report))
    return 0


def cmd_schema(_: argparse.Namespace) -> int:
    sys.stdout.write(schema_text())
    return 0


def cmd_bom_check(a: argparse.Namespace) -> int:
    probs = bom.problems(bom.load(), paid_path_only=a.paid_path)
    if probs:
        print("\n".join(probs))
        return 1
    print("bom ok")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mat", description="Music audio transcriber")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("transcribe", help="audio -> NoteEvents JSON and MIDI")
    t.add_argument("file")
    t.add_argument("--instrument", required=True, choices=["voice", "bass"])
    t.add_argument("-o", "--out", help="output directory (default: next to the input)")
    t.add_argument("--json", action="store_true")
    t.set_defaults(fn=cmd_transcribe)

    s = sub.add_parser("synth", help="synthetic data")
    ssub = s.add_subparsers(dest="synth_cmd", required=True)
    g = ssub.add_parser("generate", help="render a recipe to audio plus ground truth")
    g.add_argument("--recipe", required=True)
    g.add_argument("--out", required=True)
    g.add_argument("--name", default="clip")
    g.add_argument("--json", action="store_true")
    g.set_defaults(fn=cmd_synth_generate)
    f = ssub.add_parser("fetch-soundfont", help="download MuseScore_General (MIT) and verify it")
    f.add_argument("--json", action="store_true")
    f.set_defaults(fn=cmd_fetch_soundfont)

    e = sub.add_parser("eval", help="score transcribers on synthetic and real clips")
    e.add_argument("--suite", default="mono", choices=["mono"])
    e.add_argument("--renderer", default="tone", choices=["tone", "fluidsynth"])
    e.add_argument("--n", type=int, default=24)
    e.add_argument("--seed", type=int, default=0)
    e.add_argument("--real-dir")
    e.add_argument("--json", action="store_true")
    e.set_defaults(fn=cmd_eval)

    sc = sub.add_parser("schema", help="print the NoteEvents v1 JSON Schema")
    sc.set_defaults(fn=cmd_schema)

    b = sub.add_parser("bom", help="bill of materials")
    bsub = b.add_subparsers(dest="bom_cmd", required=True)
    bc = bsub.add_parser("check", help="fail on incomplete rows")
    bc.add_argument(
        "--paid-path", action="store_true", help="also fail on unreviewed paid-path rows"
    )
    bc.set_defaults(fn=cmd_bom_check)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args))
    except (FileNotFoundError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
