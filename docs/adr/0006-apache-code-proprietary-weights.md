# ADR-0006: Code is Apache-2.0-compatible; weights and datasets are separate and proprietary

- Status: Accepted
- Date: 2026-11-22
- Deciders: Jian (asked for advice, proposed Apache-2.0)

## Context

The product is a paid SaaS. A code licence says nothing about weights or data, and an Apache-2.0 repo lets
anyone host a clone of the code. The moat is trained weights, the data engine, and the product. Research found
GPL in several tempting pieces (Pedalboard, DawDreamer, YourMT3, Tony, probably the MuseScore CLI).

## Decision

1. This repo's code is Apache-2.0 and the repo is public (decided 2026-11-22 when the repo was created;
   this supersedes the earlier plan to wait until first release). Dependencies stay Apache-compatible.
2. Trained weights and generated datasets are **not** covered by the code licence and are not published.
3. No GPL or AGPL code is imported into the service path. GPL tools may be used offline for data generation only
   (ADR-0004). LGPL (FluidSynth) is used as a separately loaded library. A dependency register lists each
   dependency with its licence, checked in CI.
4. sibei-score stays MIT and its own repo.

## Alternatives considered

| Option | Why not |
|---|---|
| AGPL to deter hosted clones | Narrows contributors and deps, and the real moat is not the code |
| Publish weights under Apache-2.0 | Gives away the product, and may be wrong if any data is review-flagged |
| Proprietary code | Possible later (sole copyright holder), but no reason to close it now |

## Consequences

- A CI licence check blocks a GPL dependency from entering the service.
- Open-sourcing later is easy, closing later is not once outside contributions exist.
- This is engineering advice, not legal advice. The V10 lawyer review covers it.
