# 1940 acceptance on retained real evidence

The 8 November 2026 local acceptance exercise tested migration and mechanics against an existing historical transcription pilot. It did not rerun an entire year through live model APIs or establish independently labelled accuracy.

## Scope and result

The pilot covers physical pages 2–84: 49 Special and 3,456 Common entries, 3,505 total. Page 1’s 33 Special entries remain excluded.

| Result | Count |
|---|---:|
| Settled | 3,058 |
| Corrected against the earlier baseline | 84 |
| Uncertain | 363 |
| Total | 3,505 |

All retained RC1 field texts and dispositions survived migration semantically; the harness has a different CSV schema. All 95 original holds were accounted for: 45 settled and 50 uncertain. This acceptance imported existing decisions rather than claiming fresh adjudication of every entry.

The import preserved 10,988 reading variants across 3,504 IDs, including 10,661 recorded as blind and 327 informed. The remaining corrected-crop entry is covered by a retained informed decision. A separate import retained 497 final informed decisions. Full original request settings are absent for 6,547 reading variants; the surviving prompt hashes and source records were preserved without inventing missing settings. These imports are not current-protocol cache hits.

A five-case purposive batch covered agreement, punctuation, possible printer error, corrected cropping, informed judgment, and unresolved source text. It produced two settled entries, one corrected entry, and two uncertain entries. The source checks were candidate-exposed model visual review, not independent human labels. This batch is a regression exercise, not a random accuracy sample.

An import interrupted after 500 records resumed for the remaining 10,488 and added zero records on a subsequent run. Both release CSVs replayed byte-identically in a fresh process with network connections refused and no network attempts. Fault tests injected exceptions; no operating-system kill or live-provider outage test is claimed.

## Cost and remaining work

Incremental paid transcription calls: zero. Incremental provider transcription spend: $0. This does not mean the earlier readings, coding, or review were free. Historical indexed provider spend was $28.29449543, with a separate $0.050240 unresolved timeout reserve; these are ledger records, not a fully reconciled invoice.

The remaining inventory contains 1,288 distinct entries: 363 uncertain and 925 with weaker evidence. No further paid reads were planned in this acceptance exercise. Retained sample labels and same-sample post-repair scores do not establish independent true accuracy.

## Reproducibility boundaries

The code and synthetic tests are public; the real-source corpus and detailed acceptance records are retained privately. Readers can reproduce the synthetic workflow and inspect the machinery, but cannot independently reproduce this real-source acceptance from this repository alone. Aggregate results are a maintainer report.

The accepted harness revision was `5956150575d85669144bdcce205bcc000d075560`, with 58 offline tests. Publication preparation adds a history-scanner correction and a deleted-secret regression, producing 59 passing tests. That change does not alter transcription logic or the private acceptance outputs.

| Retained release | SHA-256 |
|---|---|
| Full pilot migration | `8a2056cddef630f56385cf237445698f099781cb03ca1ec5dd33da256484c89a` |
| Five-case batch | `4e7c13ce5e90dda1ae8621bfc92d6fddda7a7615a1eb9dc2a6f0e56d96555475` |

The defensible result is a reusable harness demonstrated on retained real evidence, with explicit provenance and uncertainty. A complete-year edition, independent human validation, and transfer across the full series remain separate milestones.
