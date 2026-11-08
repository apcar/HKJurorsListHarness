# Staged-command authority and compatibility — 8 November 2026

1. Offline reproduction found the separate adjudicate CLI stage computed dispatch authority but enforced it only for the read stage. The command now refuses both paid stages unless the existing run-ID authorization and cap controls pass. The reproduction used a patched local function, not a live provider.
2. Separate compare/sample/queue CLI stages previously consumed unfiltered ledger readings, bypassing the compatibility filtering used by the complete run. They now use the shared current-request filter. A changed reader temperature no longer contributes a stale candidate to a newly constructed queue.
3. Both regressions failed before the fix. The final offline suite now passes 58 tests. This is a narrow correction of existing command paths, not new orchestration functionality or spending authority.
