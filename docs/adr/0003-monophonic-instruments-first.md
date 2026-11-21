# ADR-0003: Voice and bass first, then piano, drums, guitar

- Status: Accepted
- Date: 2026-11-22
- Deciders: Jian (G2, accepting the recommendation)

## Context

Two constraints point the same way. Commercially, monophonic pitch tracking (pYIN, SwiftF0) needs no
learned weights from NC data (ADR-0001). Notationally, sibei-score handles one melody staff today, and piano
(grand staff), drums (percussion staff) and guitar (tab) need new notation work there (ADR-0002).

## Decision

Build order: **voice and bass** (monophonic, single staff) → **piano** (own polyphonic model; needs grand staff)
→ **drums** (own model on E-GMD/Groove/synthetic; needs percussion staff) → **guitar** (own model on GuitarSet +
synthetic; staff first, tab later). The user picks the instrument at upload; auto-detection is deferred.

pYIN is the first tracker. SwiftF0 is a candidate only after its training-data terms are verified, and its
46.9 Hz floor sits above bass low E (about 41 Hz), so it needs a check before bass use. pYIN takes a configurable
lower bound.

## Alternatives considered

| Option | Why not |
|---|---|
| Piano first (best data, best pretrained models) | Best models are NC-tainted, and the sheet output needs a grand staff sibei-score lacks |
| All five at once | Five models and three notation extensions before anything ships |

## Consequences

- The first shippable product is a melody-to-lead-sheet tool, which is also what sibei-score already is.
- Real videos where someone sings and plays are unsupported until separation (V7) lands. The UI says so.
- Voice with pYIN will mis-segment vibrato, glides and breaths. The review-flag flow in sibei-score is the
  mitigation, and per-note confidence is how we feed it.
