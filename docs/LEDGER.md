# Ledger

The compatibility schema is **LEDGER-v1**, one JSON object per line, append only. A correction is a new line whose `supersedes` names the earlier `attempt_id`. Old lines are not edited.

Extension fields use `schema_ext` = `LEDGER-ext-v1`:

| Field | Meaning |
|---|---|
| `attempt_id` | Unique id for this attempt |
| `provider` | `openrouter`, `gemini`, or `scripted` |
| `provider_request_id` | Id returned by the provider, when there is one |
| `input_sha256` | Prompt and image hashes |
| `raw_response_relpath` | `raw/<attempt_id>.json`, written before the ledger line |
| `reservation_usd` | Worst-case amount reserved before the attempt |
| `unresolved_charge_reserve_usd` | Kept when the charge is unknown, including a timeout |
| `http_status` | Provider status, or null |
| `billing_error` | True on HTTP 402 or a billing phrase on a 4xx |
| `supersedes` | Previous attempt id, or null |

The v1 fields (`run`, `ts`, `year`, `page`, `line_id`, `model`, `model_reported`, `step`, `reason`, `prompt_version`, `settings`, `attempt`, `tokens_in`, `tokens_out`, `cost_usd`, `wasted`, `wasted_reason`, `wall_secs`, `reviewer`, `reviewer_minutes`, `outcome`, `crop_sha256`) keep their original meanings. `line_id` is the stable entry id. `tokens_out` includes thinking tokens when the provider reports them. `cost_usd` is the provider-reported cost when present, otherwise tokens times the configured price. A timeout stores cost 0 and holds the worst-case reserve instead of inventing a charge.

`step` is `probe`, `reader_a`, `reader_b`, or `adjudication`. Probes are wasted by policy (`wasted_reason` = `billing probe overhead`) even when the call succeeds. Waste is summed on its own. Reviewer minutes are summed on their own and are not converted into dollars.

Reservations live in `reservations.jsonl` (`open`, `reconciled`, `unknown`). The derived `LEDGER-INDEX.jsonl` inside a release drops duplicate keys `(ts, line_id, model, attempt, step)` and does not rewrite the source ledger. The release index omits raw response text; the run ledger and `raw/` keep it.

`ledger` reports measured dollars per 1,000 included entries as measured cost divided by included entries, times 1,000. Unknown reserves and inherited evidence are separate figures.
