# ADR-0004: Synthetic data is generated from recipes, rendered headless, and logged in a BOM

- Status: Accepted
- Date: 2026-11-22
- Deciders: Jian (asked for heavy synthetic data; renderer choice delegated)

## Context

Synthetic (symbolic score, then rendered audio) data gives exact ground truth for both transcription and
separation, and under ADR-0001 it is also the only training data whose licence we fully control. Ableton runs
only on Windows/macOS with no headless mode, and this machine is WSL2 with no GPU. The main risk of synthetic
data is the sim-to-real gap. Research found Pedalboard and DawDreamer are GPLv3 and several free soundfonts have
unclear sample provenance.

## Decision

1. A clip is a **recipe**: seed, symbolic source (score or MIDI), instrument/patch choices, soundfont or
   sample set, effects chain. The recipe alone regenerates the clip, so audio is a cache and the recipe is the truth.
   Ground truth is the symbolic source (a score in sibei-score's model where possible, otherwise MIDI).
2. Rendering is headless and CPU: FluidSynth (LGPL) with soundfonts, and sfizz (BSD-2) with SFZ libraries. No Ableton.
3. Realism comes from many patches per instrument, plus augmentation: room IRs, EQ, noise, tape and mp3 codec,
   level and mic-distance variation. Pedalboard and DawDreamer are used **only offline** for data generation
   (never imported by service code), and the lawyer reviews that use at V10.
4. Symbolic sources come from the clean list only: procedurally generated music, public-domain scores
   (Mutopia items marked PD or CC BY, IMSLP PD), and our own compositions. Lakh MIDI and Slakh are
   not used for training until the lawyer clears the underlying-composition question.
5. Sound sources are CC0/MIT first (VCSL, MuseScore_General as listed). GeneralUser GS is usable for
   rendering but its sample provenance is unconfirmed. A BOM row exists for every one, and the BOM records the
   rendering-to-train terms as "unverified" until checked.
6. Every eval reports a **sim-to-real gap**: score on synthetic held-out minus score on real held-out.

## Alternatives considered

| Option | Why not |
|---|---|
| Ableton / commercial DAW | Not scriptable on this host, not reproducible in CI, licence per seat |
| Slakh2100 as the training base | CC BY dataset, but the Lakh MIDI under it is scraped, mostly copyrighted compositions |
| Train on MAESTRO, MUSDB etc. | NC licences, see ADR-0001 |

## Consequences

- We own the data engine, and it is reproducible from a git SHA plus a recipe file.
- Synthetic piano and guitar from soundfonts sound thin, so first models will be weaker on real recordings.
  The gap number tells us when real recordings (that we record or license) are needed.
- Singing voice cannot be rendered convincingly with soundfonts. DiffSinger (Apache-2.0) is a later option,
  voicebank licences unchecked. Voice therefore stays on pYIN for now (ADR-0003).
