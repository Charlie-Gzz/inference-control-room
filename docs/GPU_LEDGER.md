# GPU ledger

One row per GPU run. Billed seconds are wall-clock seconds of the remote call
(queue + container startup + execution), so they are an upper bound on what Modal bills.
Cost = seconds x (GPU + requested CPU + requested memory) at the rates in
`src/icr/config.py`. Rendered from `results/gpu_ledger.jsonl` by `icr.ledger`.

| Date (UTC) | Purpose | Budget | GPU | CPU | Mem GiB | Billed s | Cost $ | Total $ |
|---|---|---|---|---|---|---|---|---|
| 2026-11-14 01:19 | download models + data (CPU only) | dev | none x0 | 2 | 4 | 150 | 0.005 | 0.005 |

## Totals

- dev: $0.01 of $10.00
- fleet: $0.00 of $18.00
- h100: $0.00 of $7.00
- **all: $0.01 of $35.00**
