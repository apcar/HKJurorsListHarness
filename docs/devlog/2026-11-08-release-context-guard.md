# Immutable release context guard — 8 November 2026

1. A further offline regression reproduced an additional stale-result path: publish returned an existing immutable release after a material request setting changed, even though the new ledger-selection filter rejected the old decision.
2. Release creation now retains the current entry/field context and full expected request identities. Reusing an existing release requires an exact match. Changed or unrecorded context raises an explicit error requiring a new release identifier; historical releases are not overwritten or silently upgraded.
3. The same current-request builder is shared with ledger filtering. No new inference or larger orchestration framework was added. The complete offline suite now passes 56 tests, including the new regression; the earlier 55-test record remains a valid historical checkpoint.
