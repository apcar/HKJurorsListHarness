# Design choices

The 2026-11-08 design left several choices open and marked them “you decide”. This is what the harness does.

1. **Package, not a copy of the pilot scripts.** The 1940 scripts hard-coded machine paths, a single cap, and an experimental ladder. The harness keeps the pipeline, the ledger, the strict comparison, the single adjudication, and the closeout. It does not keep the ladder, the path strings, or the 1940-only file layout.

2. **1940 byte-for-byte replay is a checker, not a vendored edition.** Gate 6 of the design asks for a 3,505-row CSV with a specific SHA-256. Those artifacts are private evidence and are not in this repository. `verify-1940` checks them when they are supplied from outside. The new release writer has its own columns and is tested on the synthetic year. It does not claim to emit the historical bytes.

3. **Reader pair.** The example network config names strict Sonnet 5.5 via OpenRouter and Flash via the Gemini route, which is the design’s recommendation. Both are config. Haiku is not a third reader. There is no Pro route and no automatic substitution. The synthetic demo uses the `scripted` provider so it can run with no key; that provider cannot be mixed with a network provider.

4. **SciPy is not required.** Finite-population intervals use `math.comb` and an integer comparison for the 2.5% tails. Replay stays on the standard library.

5. **HTTP client.** Calls use `urllib` in the standard library. Billing stop, no 4xx retry, at most two retries on 5xx or timeout, and unknown reserves match the pilot client. A generic transport error that is not a timeout is not retried, and its reserve is held when the charge is unknown.

6. **Page 1.** Rows are dropped only when the inventory says `included=false` and gives a reason. The harness does not omit page 1 on its own.

7. **Concurrency.** Values other than 1 are a configuration error.

8. **Dispatch gate.** `authority.dispatch`, a total cap, every stage budget, a price ceiling, and `JURORS_HARNESS_AUTHORIZE` equal to `run_id` are all required. Network routes also need their environment variable to be set. Missing any of these means a plan, not a call.

9. **Priors.** Lexicon and cross-year names are post-read flags. They are not blind-read inputs. Revealing them at adjudication is off unless `learning.reveal_priors_at_adjudication` is true, which changes the prompt version and labels the block. Reference text cannot be turned on by that switch.

10. **Candidate order.** Rotation within candidate-count groups, seeded so the phase is reproducible. The 1940 per-line shuffle is not reproduced and is not called counterbalancing.

11. **Incomplete coverage** is reported separately from the four sample strata.

12. **CORRECTED versus SETTLED.** A resolved original hold is SETTLED. CORRECTED means a non-hold baseline changed. Any unresolved required field forces UNCERTAIN.

13. **One adjudication.** HTTP 200, even with bad JSON, is the one response. Unique fields can be recovered locally. Conflicting objects are not chosen. An in-flight reservation without a saved response is not sent again unless `retry_unknown_attempts` is set, and the old reserve stays.

14. **Sample-label budget** is reserved in the cap so the allocation is honest, and this version does not spend it on a third model. It is not transferred.

15. **Leading asterisk** is ignored only in the post-hoc reference comparison of the name. The release text keeps it.

16. **License.** Left undecided, including in package metadata. No MIT or Apache choice is implied.

17. **Paths.** Config and inventory paths must be relative. A `--work` override may be an absolute scratch directory and is not copied into manifests or the release.

18. **Release index.** The copy inside the release omits raw model text. The run `ledger.jsonl` and `raw/` keep it. Redaction is for credentials, not for rewriting a transcription.
