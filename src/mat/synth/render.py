"""Renderers: a numpy tone renderer (no external tools, used by unit tests) and FluidSynth."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pretty_midi
import soundfile as sf

from mat.synth.recipe import ARTICULATION, Recipe, SymNote, beat_seconds

Audio = npt.NDArray[np.float32]

TAIL_S = 0.5

SOUNDFONT_DIR = Path.home() / ".cache" / "mat" / "soundfonts"
SOUNDFONT_NAME = "MuseScore_General.sf3"
SOUNDFONT_SHA256 = "5b85b6c2c61d10b2b91cddd41efcce7b25cd31c8271d511c73afafbef20b6fa3"
_SF_BASE = "https://ftp.osuosl.org/pub/musescore/soundfont/MuseScore_General"
DOCKER_IMAGE = "mat-fluidsynth"


def note_times(recipe: Recipe, notes: list[SymNote]) -> list[tuple[float, float, int]]:
    """(onset_s, offset_s, pitch) as played: each note sounds for ARTICULATION of its length."""
    b = beat_seconds(recipe)
    return [
        (n.onset_beat * b, (n.onset_beat + n.dur_beat * ARTICULATION) * b, n.pitch) for n in notes
    ]


def _midi_hz(pitch: int) -> float:
    return float(440.0 * 2.0 ** ((pitch - 69) / 12.0))


def render_tone(recipe: Recipe, notes: list[SymNote]) -> Audio:
    sr = recipe.sample_rate
    timed = note_times(recipe, notes)
    total = max(off for _, off, _ in timed) + TAIL_S
    out = np.zeros(int(np.ceil(total * sr)), dtype=np.float64)
    for onset, offset, pitch in timed:
        f0 = _midi_hz(pitch)
        n_on = int(round(onset * sr))
        n_len = int(round((offset - onset + 0.05) * sr))
        t = np.arange(n_len) / sr
        if recipe.patch == "sine":
            weights = [1.0]
        elif recipe.patch == "pluck":
            weights = [1.0, 0.6, 0.35, 0.2, 0.1]
        else:  # saw
            weights = [1.0 / h for h in range(1, 13)]
        wave = np.zeros(n_len)
        for h, w in enumerate(weights, start=1):
            if f0 * h < sr / 2:
                wave += w * np.sin(2 * np.pi * f0 * h * t)
        env = np.ones(n_len)
        a, r = int(0.01 * sr), int(0.05 * sr)
        env[:a] = np.linspace(0, 1, a)
        env[-r:] = np.minimum(env[-r:], np.linspace(1, 0, r))
        if recipe.patch == "pluck":
            env *= np.exp(-t * 2.5)
        seg = wave * env
        end = min(len(out), n_on + n_len)
        out[n_on:end] += seg[: end - n_on]
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak * 0.5).astype(np.float32)


# --- FluidSynth -------------------------------------------------------------------------------


def fetch_soundfont() -> Path:
    """Download MuseScore_General (MIT; see bom/sources.toml) and verify its checksum."""
    SOUNDFONT_DIR.mkdir(parents=True, exist_ok=True)
    dest = SOUNDFONT_DIR / SOUNDFONT_NAME
    if not (dest.exists() and _sha256(dest) == SOUNDFONT_SHA256):
        urllib.request.urlretrieve(f"{_SF_BASE}/{SOUNDFONT_NAME}", dest)  # noqa: S310
        if _sha256(dest) != SOUNDFONT_SHA256:
            dest.unlink()
            raise RuntimeError("soundfont checksum mismatch")
    lic = SOUNDFONT_DIR / "MuseScore_General_License.md"
    if not lic.exists():
        urllib.request.urlretrieve(f"{_SF_BASE}/MuseScore_General_License.md", lic)  # noqa: S310
    return dest


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def soundfont_path() -> Path | None:
    p = SOUNDFONT_DIR / SOUNDFONT_NAME
    return p if p.exists() else None


def fluidsynth_available() -> bool:
    if shutil.which("fluidsynth"):
        return True
    if shutil.which("docker"):
        r = subprocess.run(
            ["docker", "image", "inspect", DOCKER_IMAGE], capture_output=True, check=False
        )
        return r.returncode == 0
    return False


def _fluidsynth_cmd(sf: Path, mid: Path, wav: Path, sr: int) -> list[str]:
    args = [
        "-ni",
        "-g",
        "1.0",
        "-r",
        str(sr),
        "-o",
        "synth.reverb.active=0",
        "-o",
        "synth.chorus.active=0",
        "-F",
        str(wav),
        str(sf),
        str(mid),
    ]
    if shutil.which("fluidsynth"):
        return ["fluidsynth", *args]
    # Docker fallback: mount the soundfont dir and the work dir at identical paths.
    mounts = {str(sf.parent), str(mid.parent)}
    cmd = ["docker", "run", "--rm", "--user", f"{_uid()}"]
    for m in sorted(mounts):
        cmd += ["-v", f"{m}:{m}"]
    return [*cmd, DOCKER_IMAGE, "fluidsynth", *args]


def _uid() -> str:
    import os

    return f"{os.getuid()}:{os.getgid()}"


def render_fluidsynth_timed(
    timed: list[tuple[float, float, int]],
    program: int,
    is_drum: bool,
    bpm: float,
    sample_rate: int,
    soundfont: str | None = None,
) -> Audio:
    """Render (onset_s, offset_s, pitch) notes with one General MIDI program, or the drum kit."""
    sf_file = Path(soundfont) if soundfont else soundfont_path()
    if sf_file is None or not sf_file.exists():
        raise FileNotFoundError("soundfont missing: run `mat synth fetch-soundfont`")
    if not fluidsynth_available():
        raise RuntimeError("fluidsynth not found (install it, or `make docker-fluidsynth`)")
    pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    inst = pretty_midi.Instrument(program=program, is_drum=is_drum)
    for onset, offset, pitch in timed:
        inst.notes.append(pretty_midi.Note(velocity=90, pitch=pitch, start=onset, end=offset))
    pm.instruments.append(inst)
    with tempfile.TemporaryDirectory(prefix="mat-fs-") as tmp:
        mid, wav = Path(tmp) / "in.mid", Path(tmp) / "out.wav"
        pm.write(str(mid))
        subprocess.run(
            _fluidsynth_cmd(sf_file, mid, wav, sample_rate),
            check=True,
            capture_output=True,
            timeout=120,
        )
        data, sr = sf_read(wav)
    if sr != sample_rate:
        raise RuntimeError("unexpected sample rate from fluidsynth")
    tail = np.zeros(int(TAIL_S * sr), dtype=np.float32)
    peak = float(np.max(np.abs(data))) or 1.0
    return np.concatenate([data / peak * 0.5, tail]).astype(np.float32)


def render_fluidsynth(recipe: Recipe, notes: list[SymNote]) -> Audio:
    program = int(recipe.patch.split(":", 1)[1]) if recipe.patch.startswith("gm:") else 0
    return render_fluidsynth_timed(
        note_times(recipe, notes), program, False, recipe.bpm, recipe.sample_rate, recipe.soundfont
    )


def sf_read(path: Path) -> tuple[Audio, int]:
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return data.mean(axis=1).astype(np.float32), int(sr)


def render(recipe: Recipe, notes: list[SymNote]) -> Audio:
    if recipe.renderer == "fluidsynth":
        return render_fluidsynth(recipe, notes)
    return render_tone(recipe, notes)
