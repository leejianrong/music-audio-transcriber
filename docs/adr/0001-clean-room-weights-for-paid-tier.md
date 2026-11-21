# ADR-0001: Paid-tier models use our own weights; pretrained models are dev-only

- Status: Accepted
- Date: 2026-11-22
- Deciders: Jian (F1 + G1, accepting the recommendation)

## Context

The product is a paid SaaS. Research on 2026-11-22 (see QUESTIONS.md Q-research) found no pretrained
transcription or separation model with a clearly commercial-safe weights licence. Code is mostly MIT or
Apache-2.0, but weights are trained on MAESTRO (CC BY-NC-SA), MUSDB18 (non-commercial), MedleyDB, MoisesDB,
or carry no stated licence. The Demucs author says he cannot grant a licence for the weights. Whether
NC-trained weights inherit the NC restriction is unsettled law, not something we can resolve here.

## Decision

1. Every model that serves a **paying user** runs on weights we trained ourselves, on data whose licence
   permits commercial training (CC0, CC BY, public domain, our own synthetic data, or stems we licence).
2. Pretrained third-party models are allowed for **development, benchmarking and a private alpha only**. They
   sit behind the `Transcriber` / `Separator` protocols so that swapping them out is a config change.
3. Monophonic instruments (voice, bass) use signal-processing pitch trackers with no learned weights
   (librosa pYIN first), so they are shippable commercially from day one.
4. Before any paid launch, an IP lawyer reviews the data bill of materials and the weights question (slice V10 gate).
5. Every dataset, soundfont, IR and pretrained model is recorded in a bill of materials with its licence and the
   URL it was read from. Nothing enters training without a BOM row.

## Alternatives considered

| Option | Why not |
|---|---|
| Ship pretrained weights (htdemucs, Basic Pitch, ByteDance) and accept the risk | Founder-level legal exposure for a paid product, and the Demucs author himself declines to grant rights |
| Wait for a lawyer before building anything | Dev and benchmarking use of pretrained models is low risk and gives us the quality targets we need |
| Seek written commercial licences from weight authors | Worth trying in parallel (cheap), but cannot be the plan: many authors are anonymous or unreachable |

## Consequences

- Training our own models is mandatory, not optional. That makes GPU budget (F5) a real input, so F5 is
  revisited before V4.
- Our weights may be worse than pretrained ones at first. The eval harness measures the gap against pretrained
  baselines on the same held-out data so the cost is visible.
- Separation is the hardest case: there is no clean real-stem dataset beyond a-cappella VocalSet. It will need
  synthetic data, licensed stems, or a lawyer-approved risk decision (Open risk in PLAN.md).
- Evaluating on NC test sets (MAESTRO test, MUSDB18 test) is treated as internal benchmarking, not training.
  The lawyer confirms this at V10.
