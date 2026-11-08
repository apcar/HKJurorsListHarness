# 2026-11-08 — initial harness

The 1940 pilot was a set of one-off scripts: a blind reread, a strict compare, an adjudication pass, and a closeout client with a hard cap. This devlog records the first reusable package built from that design. No paid provider was called while writing it. The only end-to-end run in the tree is the synthetic fixture.

What was built:

- A config-driven year pipeline with two blind readers, strict comparison, one adjudication queue, explicit UNCERTAIN, post-hoc reference flags, a stratified sample, and a versioned release.
- A router that probes, reserves a worst-case charge, stops on the first billing error, does not retry 4xx, retries 5xx and timeouts at most twice, and does not fall back to another provider.
- An append-only LEDGER-v1 JSONL with a derived index. Restart skips a completed call instead of paying again.
- Replay from baseline, overlay, and dispositions, with no network.

What was not done:

- No 1939, 1941, or 1938 edition. Those years were a recommendation in the design, not an authorization to spend.
- The 1940 RC1 byte-for-byte check cannot be run here. The retained CSV, baseline, and scans are not in this repository, and they should not be added until rights are settled.
- No human-review application. Only the uncertain-line export exists.

Measured spend for this commit is zero provider dollars. The synthetic demo records scripted micro-costs so the ledger and the per-thousand figure have something to add up; those numbers are fixtures.

Publication is not requested by this commit. The license file is still undecided on purpose.
