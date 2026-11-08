# Pipeline, resume, and replay

## Stages

| Command | What it writes |
|---|---|
| `validate` | Nothing. Checks caps, routes, and prompt files. |
| `census` | `census/CENSUS.json`, frozen inventory, manifest. |
| `crops` | `crops/CROP-INDEX.csv` with SHA-256. |
| `freeze` | Census, crops, and `baseline/BASELINE.csv`. Refuses a changed baseline. |
| `plan` | `PLAN.json` with prompt hashes and worst-case reservations. |
| `read` | Blind calls for reader A, then reader B, after a probe on each route. |
| `compare` | `compare/COMPARISON.csv`. |
| `sample` | `sample/SAMPLE-FRAME.csv`. Kept once the seed is frozen. |
| `queue` | `queue/FINAL-QUEUE.json` and the candidate-order audit. |
| `adjudicate` | One call per queued entry, after a probe. |
| `release` | The release directory: dispositions, overlay, scores, cost, closeout, uncertain export. |
| `replay` | A new CSV from a release directory. |
| `status` | Prints `RESUME.md`. |
| `ledger` | Measured dollars, waste, reserves, and dollars per 1,000 included entries. |
| `run` | The stages in order. |

`closeout` and `export-uncertain` assemble the same release. The closeout and the uncertain export are part of that directory, not a second edition.

## Work directory

```
work/
  RESUME.md
  RESUME.json
  PLAN.json
  ledger.jsonl
  reservations.jsonl
  prompts-sent.jsonl
  BILLING-STOP.json          # only after a billing error
  raw/<attempt-id>.json
  census/
  crops/
  baseline/
  compare/
  sample/
  queue/
  learning/
  release/<release-id>/
```

`config.snapshot.json` is a copy of the config file that was passed in. It keeps relative paths. The scratch directory itself is not written into the release.

## Resume

`run` always refreshes `RESUME.md`.

Completed ledger rows are the cache. A row matches when year, crop hash, stage, model, prompt version, and entry id match. A successful row is reused. An adjudication row with HTTP 200 is also reused, even if the JSON was malformed, because that was the one deliberation. Recovery of unique field objects is local and is recorded in `PARSER-REPAIRS.jsonl`.

A timeout stores `unresolved_charge_reserve_usd` for the worst-case reservation. Later calls see that reserve. It is not released to make room.

## Replay

Inputs are `inputs/BASELINE.csv`, `OVERLAY.csv`, and `DISPOSITIONS.csv`. The writer uses a fixed column order, UTF-8, and `\n` line endings. `verify-release` rebuilds the CSV and compares bytes with `<release-id>.csv`.

Reference files are not replay inputs. Crop bytes are not required to rebuild the CSV. Hash checks against crop files belong to the crop stage, which runs before any call.

## Sample strata

Mutually exclusive, in this order:

1. `held_or_source_loss` — inventory hold, scan loss, or ownership problem
2. `reader_disagreement` — any field differs under NFC
3. `agreement_with_risk` — strict agreement plus an accent, abbreviation dot, meaningful mark, edge contact, or normalization hazard
4. `other_agreement`

Entries with fewer than two usable readings, and no source-loss hold, are `incomplete_coverage`. They stay in the year denominator and in the closeout. They are not one of the four probability strata, and a reference file is not a stratum.

When a stratum is smaller than its allocation, the sample takes the whole stratum and records that census. Purposive `hard_reason` rows go to `HARD-CASES.csv` and are not extra sample observations.

## Dispositions

- **SETTLED** — resolved, and the release text matches a settled baseline, or an original hold is now fully resolved.
- **CORRECTED** — resolved, and at least one field differs from a baseline that was not an original hold.
- **UNCERTAIN** — any required field is unresolved. Reason codes include `unread-for-budget`, `model-split`, `missing-scan-text`, `source-illegibility`, `normalization-conflict`, `ownership`, `parser-incomplete`, `missing-evidence`, and `transport-exhausted`.
- **EXCLUDED** — the inventory marked the row out, with a reason.

Unread rows keep baseline text and `operational_state` of `pending_budget` or `billing_stopped`. They are not settled. A field that was reviewed and still has no defensible reading is `[UNRESOLVED]`, unless the reading itself contains `[?]` or `[illegible]`.
