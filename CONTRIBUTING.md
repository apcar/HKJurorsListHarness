# Contributing

This harness transcribes print as it stands. A change that modernises a name, expands `Ld.` to `Ltd.`, or drops an abbreviation dot is a transcription error even when the result is easier to read.

## Do not commit

- API keys, `.env`, or authorization headers
- Scans, crops from a real witness, ledgers, or run directories
- Reference transcriptions, including Gwulo text
- Absolute machine paths

`runs/`, `data/`, `scans/`, `ledgers/`, and `.env` are gitignored. A gitignore does not clean history. Run `python scripts/secret_scan.py --history` before any future publication, and stop if it reports a finding.

## Prompts

Add a new prompt as a new file and a new `prompt_version`. Do not edit a prompt that a run has already used. The cache key includes that version; changing the text in place would either reuse the wrong reading or hide a policy change.

Blind prompts take an entry id and a year. Do not add parameters for the baseline, the other reader, a lexicon row, a cross-year name, or a reference.

## Tests

`pytest` must pass. New paid-call behaviour needs a mocked provider test. Do not add real images or real juror lines as fixtures.

## License

Code contributions are intended for distribution under the repository’s MIT license. Do not contribute third-party source material without appropriate rights. Historical inputs and outputs have separate rights; see DATA-NOTICE.md.
