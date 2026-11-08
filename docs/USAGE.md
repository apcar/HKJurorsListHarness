# Using the harness

[Back to the project overview](../README.md). Run commands from the repository root.

## Pipeline

For one year, witness, and edition:

1. **Census** the supplied inventory. A detector count, a reference count, and a source-derived count stay separate. None of them is a completeness certificate.
2. **Freeze** a baseline and a manifest. The baseline is a comparison text, not the source.
3. **Hash crops.** A changed file is a new hash, not a silent overwrite.
4. **Two blind readers.** Each sees the crop, the field schema, and a versioned prompt. Neither sees the other reader, the baseline, a reference, cross-year names, or a line-specific typo note.
5. **Strict comparison** under Unicode NFC. Punctuation, spaces, accents, abbreviation dots, internal line breaks, and marks all count.
6. **Dedupe** unresolved fields into one case. Identical candidate text keeps every evidence id.
7. **One adjudication.** Candidates are anonymous and scan-derived. The order is counterbalanced, not described as a shuffle. There is no second deliberation and no provider fallback.
8. **Disposition.** Each included entry is SETTLED, CORRECTED against the frozen baseline, or UNCERTAIN. Excluded inventory rows are EXCLUDED, with a reason. Operational state (billing stop, missing crop, budget) is a separate column.
9. **Reference flags,** only after decisions, and only as field names. A mismatch does not buy another reading and does not change the decision.
10. **Stratified sample,** frozen before adjudication.
11. **Release candidate** plus a closeout-and-omissions note, and an `UNCERTAIN-LINES-v1` export for a future review tool.

## Install

Python 3.11 or newer. The runtime dependency set is the standard library.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

From a checkout you can also run `python -m jurors_harness` without installing.

## Run the synthetic year

The checked-in year is fake. Names such as Alfa Example are fixtures, not jurors. The provider is `scripted`, so the demo does not call the network and does not need a key. It still goes through probes, the ledger, reservations, and the release.

```bash
export JURORS_HARNESS_AUTHORIZE=synthetic-1939-demo
python -m jurors_harness run \
  --config configs/examples/synthetic-year.json \
  --work runs/synthetic-1939-demo
```

`JURORS_HARNESS_AUTHORIZE` must equal the config `run_id`. Without it the command freezes the inventory, writes `PLAN.json` and `RESUME.md`, and does not dispatch.

A real route file, with dispatch left off, is `configs/examples/openrouter-gemini.json`. Copy it, point `inputs_dir` at your own inventory, set caps, and keep `authority.dispatch` false until a plan looks right.

## Run a real year

Prepare three inputs, using paths relative to the repository root:

- `inventory.csv` with one row per entry. Included and excluded rows both belong in the file. Page 1 stays if it is in the inventory; the 1940 omission of page 1 is not a template.
- `census.json` stating whether a source census is actually established, plus detector, reference, and source-derived counts as separate measures.
- Crop files named by the inventory. Optional `reference.csv`, `priors.csv`, and `lexicon.jsonl` are flags only.

Set `authority.dispatch` to true only when the caps are real. Export `OPENROUTER_API_KEY` and `GEMINI_API_KEY` as needed. Keys are read from the environment at call time and are not written to the ledger.

```bash
python -m jurors_harness validate --config path/to/year.json
python -m jurors_harness plan --config path/to/year.json
export JURORS_HARNESS_AUTHORIZE=<the run_id>
python -m jurors_harness run --config path/to/year.json
```

Individual stages are the same commands: `census`, `freeze`, `crops`, `read`, `compare`, `sample`, `queue`, `adjudicate`, `release`, `ledger`, `status`.

Dispatch also requires a total cap, a budget for every stage (`probe`, `reader_a`, `reader_b`, `adjudication`, `sample_label`), and a per-call price ceiling. Stage budgets must fit in the total. Unused budget is not moved to another stage. Concurrency above one is refused.

## Resume

Completed calls are cached using the full material request identity, including rendered prompts, candidate context, image bytes, model settings, destination, and timeout, alongside entry and stage identity. Credentials are excluded. Incompatible historical rows are not silently reused as current calls. A second `run` skips those calls. The ledger is append-only, so the restart does not pay them again.

On any stop the work directory gets `RESUME.md` and `RESUME.json`:

- A **402 or other billing error** stops every stage and every route. Nothing falls through to another provider. Resume only after the account is funded, by setting `authority.acknowledge_billing_stop` to the timestamp in `BILLING-STOP.json`. Do not delete the ledger.
- A **cap** stops before the next worst-case reservation would exceed the stage budget or the total. Unknown-charge reserves, including timeouts, stay counted.
- A **crash during a call** leaves an open reservation. That attempt is an unknown outcome. It is not treated as free, and it is not silently sent again unless `authority.retry_unknown_attempts` is set.

4xx responses are not retried. 5xx and timeouts are retried at most twice, with backoff, and each attempt reserves again.

## Replay

Replay rebuilds the release CSV from the frozen baseline, the overlay, and the dispositions. It does not call a model and it does not use the network.

```bash
python -m jurors_harness replay \
  --rcdir runs/<run-id>/release/<release-id> \
  --output /tmp/<release-id>.replayed.csv
python -m jurors_harness verify-release --rcdir runs/<run-id>/release/<release-id>
```

The output path must not already exist. `verify-release` checks byte equality with the CSV written when the release was created.

`verify-1940` checks an **externally supplied** 1940 RC1 against the frozen row count, SHA-256, and disposition totals. Those files are not in this repository. Passing the checker is not something this tree claims to have done.

## Learning and review export

A printer's-typo lexicon and cross-year name file can flag lines after the blind reads. By default those flags stay out of adjudication. Setting `learning.reveal_priors_at_adjudication` to true uses a distinct prompt version and labels the block as informed prior context, still without reference text. Blind reads never receive either file.

`UNCERTAIN-LINES-v1` JSONL, with `UNCERTAIN-INDEX.csv`, is the handoff for a future human review tool. This repository does not include that tool.

## Tests

```bash
pytest
python scripts/secret_scan.py
python scripts/secret_scan.py --history
```

The publication candidate passes 59 offline tests. Tests use synthetic fixtures and mocked providers. They cover the billing stop, 4xx, 5xx and timeout retries, resume, and caps. They do not use real scans or real transcriptions.
