# GPU ledger

One row per Modal run. **Billed s** is the time inside the container plus a 25 s startup allowance.
**Est. $** = billed seconds x (GPU + requested CPU + requested memory) at the rates
in `src/icr/config.py`. **Actual $** is what `modal billing report` shows for the
run's app (it also covers CPU or memory used above the request, and network egress).
Totals use the actual cost when it is known. Rendered by `icr.ledger`.

| Date (UTC) | Purpose | Budget | GPU | CPU | Mem GiB | Billed s | Est. $ | Actual $ | Total $ |
|---|---|---|---|---|---|---|---|---|---|
| 2026-11-14 01:19 | download models + data (CPU only) | dev | none | 2 | 4 | 150 | 0.005 | 0.043 | 0.043 |
| 2026-11-14 01:32 | M0 smoke test (AWQ, 20 requests) | dev | L4 x1 | 4 | 16 | 731 | 0.227 | 0.094 | 0.137 |
| 2026-11-14 03:38 | download models + data (CPU only) | dev | none | 2 | 4 | 33 | 0.001 | 0.000 | 0.138 |
| 2026-11-14 15:16 | M3a calibration ramp | dev | L4 x1 | 4 | 16 | 494 | 0.153 | 0.147 | 0.285 |
| 2026-11-14 15:54 | M3a: fine chat ramp, coarse rag ramp, gsm8k, greedy (awq) | dev | L4 x1 | 4 | 16 | 887 | 0.275 | 0.269 | 0.554 |
| 2026-11-14 20:05 | M3a stage 1 sweep, session 1 | dev | L4 x1 | 4 | 16 | 1017 | 0.316 | 0.309 | 0.864 |
| 2026-11-14 20:49 | M3a stage 1 sweep, session 2 | dev | L4 x1 | 4 | 16 | 1446 | 0.449 | 0.443 | 1.307 |
| 2026-11-14 21:20 | M3a stage 1 sweep, session 3 | dev | L4 x1 | 4 | 16 | 1345 | 0.417 | 0.412 | 1.719 |
| 2026-11-14 21:33 | M3a stage 1 sweep, session 4 (draft, suffix) | dev | L4 x1 | 4 | 16 | 578 | 0.179 | 0.174 | 1.893 |
| 2026-11-14 22:07 | M3a stage 2 (seqs256 x2) + suffix decoding retry | dev | L4 x1 | 4 | 16 | 1459 | 0.453 | 0.448 | 2.340 |
| 2026-11-15 01:49 | M3a finalists on rag + no-sharing calibration (awq) | dev | L4 x1 | 4 | 16 | 1126 | 0.349 | 0.343 | 2.684 |
| 2026-11-15 15:16 | M4 session 1: proxy check + chat 3 policies x 3 repeats | fleet | L4 x4 | 8 | 64 | 3625 | 4.119 | 0.000 | 2.684 |
| 2026-11-15 16:38 | M4 session 1 (second try): proxy check + chat | fleet | L4 x4 | 8 | 64 | 25 | 0.028 | 0.000 | 2.684 |
| 2026-11-15 20:06 | M4 pilot on L4:2: proxy check + chat, 3 policies x 1 repeat | fleet | L4 x2 | 5 | 32 | 1134 | 0.659 | 0.649 | 3.332 |
| 2026-11-15 21:06 | M4 session 1 (third try): proxy check + chat | fleet | L4 x4 | 8 | 64 | 25 | 0.028 | 0.000 | 3.332 |

## Notes

- 2026-11-14 01:32, M0 smoke test (AWQ, 20 requests): first estimate used wall-clock time, which included a 7-minute wait for an L4 that Modal does not bill
- 2026-11-15 15:16, M4 session 1: proxy check + chat 3 policies x 3 repeats: NEVER RAN: waited in the queue for a 4-GPU L4 machine from 20:51 EST, no container was ever started, and the client login token expired overnight. No fleet run exists. Modal billing report has no entry for this app.
- 2026-11-15 16:38, M4 session 1 (second try): proxy check + chat: NEVER RAN: queued for a 4-GPU L4 machine for 80 minutes (10:17 to 11:37 EST), no container was started, request cancelled by hand. Nothing billed.
- 2026-11-15 21:06, M4 session 1 (third try): proxy check + chat: NEVER RAN: queued for a 4-GPU L4 machine for 52 minutes (15:16 to 16:08 EST), no container was started, request cancelled by hand. Nothing billed.

## Totals

- dev: $2.68 of $10.00
- fleet: $0.65 of $18.00
- h100: $0.00 of $7.00
- **all: $3.33 of $35.00**
