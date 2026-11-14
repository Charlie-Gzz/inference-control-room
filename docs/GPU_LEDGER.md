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
| 2026-11-14 21:20 | M3a stage 1 sweep, session 3 | dev | L4 x1 | 4 | 16 | 1345 | 0.417 | 0.411 | 1.718 |

## Totals

- dev: $1.72 of $10.00
- fleet: $0.00 of $18.00
- h100: $0.00 of $7.00
- **all: $1.72 of $35.00**
