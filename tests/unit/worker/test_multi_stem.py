"""`complete` with several stems (sibei-score ADR-0034 amendment, SIB2-147)."""

from __future__ import annotations

from typing import Any

import pytest

from mat.core.note_events import NoteEvents
from mat.synth.mix import STEMS, MixRecipe, build_mix, resolve, stem_truth

from .fakes import LEASE, FakeApi

CLIP = build_mix(resolve(MixRecipe(seed=11, bars=2, bpm=100.0, sample_rate=22050)))


def stems() -> list[dict[str, Any]]:
    return [stem_truth(CLIP, s).model_dump(mode="json") for s in STEMS]


def test_several_stems_go_inline_under_a_stems_key_with_one_duration() -> None:
    api = FakeApi()
    api.client().complete_stems("job_1", LEASE, 5.0, stems())
    (done,) = api.calls("/complete")
    assert done["durationSeconds"] == 5.0
    sent = done["result"]["inline"]["stems"]
    assert [s["instrument"] for s in sent] == ["voice", "drums", "bass", "other"]
    assert len({s["source"]["sha256"] for s in sent}) == 1


def test_a_single_stem_is_still_sent_as_a_stems_list() -> None:
    api = FakeApi()
    api.client().complete_stems("job_1", LEASE, 5.0, stems()[:1])
    (done,) = api.calls("/complete")
    assert len(done["result"]["inline"]["stems"]) == 1


def test_stems_with_different_sources_are_refused_before_any_request() -> None:
    api = FakeApi()
    bad = stems()
    bad[2]["source"]["sha256"] = "f" * 64
    with pytest.raises(ValueError, match=r"stems\[2\].*sha256"):
        api.client().complete_stems("job_1", LEASE, 5.0, bad)
    assert api.requests == []


def test_stems_with_different_durations_are_refused() -> None:
    bad = stems()
    bad[1]["source"]["duration_s"] += 0.05  # the server tolerates 10 ms
    with pytest.raises(ValueError, match=r"stems\[1\].*duration"):
        FakeApi().client().complete_stems("job_1", LEASE, 5.0, bad)


def test_more_than_twelve_stems_or_none_are_refused() -> None:
    one = stems()[0]
    with pytest.raises(ValueError, match="12"):
        FakeApi().client().complete_stems("job_1", LEASE, 5.0, [one] * 13)
    with pytest.raises(ValueError, match="at least one"):
        FakeApi().client().complete_stems("job_1", LEASE, 5.0, [])


def test_the_fixtures_are_valid_note_events() -> None:
    for s in stems():
        NoteEvents.model_validate(s)
