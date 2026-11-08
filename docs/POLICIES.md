# Literal policy, decisions, and scoring

## Literal policy

Compare with Unicode NFC only. Do not case-fold, spell-correct, or collapse whitespace in order to settle a line.

Count punctuation, spaces, accents, abbreviation dots, line breaks inside a field, asterisks, and daggers. A successful JSON parse is not evidence that the print says that.

Leader dots and font styling are excluded from the instructions. If a reader emits leader dots anyway, the harness does not strip them. Equality does not silently clean a reading.

Generic prompt rules may say that `Ld.` stays `Ld.`. A line-specific lexicon entry is not copied into a blind prompt.

## Agreement

Two complete readings that are literal-equal on every required field can be SETTLED or CORRECTED by **blind agreement**. That is not a claim the line is proved correct.

The same placeholder from both readers does not settle a line when any required field is missing, a reading contains `[?]`, `[illegible]`, or `[UNRESOLVED]`, or the inventory or the reading flags ownership trouble or scan loss.

## Adjudication

One HTTP-completed adjudication per case. Transport retries are not extra deliberations. A malformed body is kept. Local recovery accepts a field only when every complete object for that field is identical. Conflicts stay unresolved. There is no paid formatting retry.

If the explanation says the reader normalised, modernised, or substituted “the real word”, that field is UNCERTAIN with reason `normalization-conflict`. The model text is not accepted and no further call is made.

Candidate labels are A, B, C in a rotation within each candidate-count group. Position counts differ by at most one. The audit file keeps the map from label to reader role. The prompt does not.

## Reference flags

After dispositions exist, an optional local reference file can mark which fields differ. The flag file stores field names, not the reference text. `decision_changed_by_reference` is always false. A missing file means the reference was not supplied, not that none exists.

For the flag only, one leading asterisk on the name is ignored so a printed mark is not reported as a name mismatch. The stored transcription keeps the asterisk.

## Scoring

The sample is frozen before adjudication. Scores compare the baseline and the release with the same model labels. Where the release adopted the label, say **same-sample post-repair**. That is not held-out accuracy and not human ground truth.

A field with no usable label stays in the denominator as unresolved. A known field discrepancy is an error even if another field is unresolved.

Practical class is separate from strict equality. A change to the case-folded, accent-stripped letters or digits, or to the asterisk or dagger count, is meaningful. Other strict differences are literal-only. Character discrepancy is Levenshtein distance on the NFC strings.

Intervals are exact equal-tailed 95% hypergeometric bounds (2.5% each tail). Unresolved labels widen the upper bound from known errors to known errors plus unresolved. The interval is about the sample, not about model-label bias, and it is not pooled across strata.

## Costs

The design’s historical all-in figure for the 1940 experiments is context for planning only. It is not a quote for this two-reader harness, and the old cap does not fund a new year. A year runs only under the caps in its own config.
