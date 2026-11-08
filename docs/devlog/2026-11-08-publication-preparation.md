# Publication preparation — 8 November 2026

The pre-publication review found that the original history scanner placed revision IDs after Git’s path separator. A clean result could therefore miss committed material. A deleted synthetic credential reproduced the failure. The replacement scans every reachable text blob, commit, and annotated tag using the same patterns as the working-tree scan, returning object IDs and line numbers without echoing matched values. The CI checkout now fetches complete history.

The publication candidate passes 59 offline tests. Historical scans and private logs are not included. The full history is retained, including the AI-assisted initial implementation. Pattern scanning reduces risk but does not prove the absence of every possible secret.

The public documentation now distinguishes synthetic execution, real-source migration, model-reviewed accuracy, and independent verification. MIT is the proposed publication license; the release is prepared privately pending Andrew’s approval. The working acceptance checkout is unchanged.
