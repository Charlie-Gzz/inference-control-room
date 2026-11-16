# Questions for Charlie

Each has a recommendation and what was done in the meantime. None of them blocked the build.

## Q1. Rerun the fleet experiments on 4 GPUs? (answered 2026-11-15)

**Context.** The plan asks for a 4-GPU fleet (`L4:4`). Three requests for it waited 50 to
80 minutes each on 2026-11-14 and 2026-11-15 and never got a container. Nothing was
billed. The plan's fallback (`L4:2`) was applied, and the chat comparison is done on 2
GPUs. With 2 replicas, round-robin lands a follow-up request on the right GPU half the
time (a quarter of the time with 4), so the routing effect on 2 GPUs is probably smaller
than on 4. The full 4-GPU plan is estimated at about $17, more than the fleet reserve
will have left after the 2-GPU runs.

**Recommendation.** Publish the 2-GPU results and try 4 GPUs again at a quieter time.
This needs a higher budget cap or a shorter run list.

**Answer (Charlie, 2026-11-15, 22:05 EST).** "I say we go for it, I still have credits
available if not, I can put $17 more for sure."

**What that changes** (Claude's reading, correct it if wrong):

- The full fleet plan is rerun on `L4:4`. The 4-GPU runs become the headline. The 2-GPU
  runs stay as a second data set.
- The budget rises by up to $17 for this: total hard stop $52 (was $35), fleet reserve
  $35 (was $18). Development ($10) and the H100 session ($7) are unchanged.
- Charlie handles Modal credits and the workspace spend limit. The build never changes
  billing or account settings.
- If `L4:4` still cannot be had after several tries at different hours, the 2-GPU
  results are the headline and the extra budget is not spent.

**Confirmed again (Charlie, 2026-11-16, about 10:58 EST):** "go 4 GPUs". The fourth
request for `L4:4` went into the queue at 11:00 EST.

**Outcome (2026-11-16, 15:32 EST).** The fourth and fifth requests (11:00 and 14:32 EST)
each waited 60 minutes without a container and were cancelled. Nothing was billed. That
is five tries on three days at five different hours. The rule above applies: the 2-GPU
results are the headline, no more `L4:4` requests are made in this build, and the budget
caps are back at the plan's values ($35 total, $18 fleet). None of the extra $17 was
spent.

## Q2. Try 4 GPUs again on another day? (open)

**Context.** A 4-GPU L4 container could not be had in five tries. One L4 was available
within 20 minutes on the same afternoon, so the shortage is specific to several L4s in
one container. The code is ready: `uv run modal run -m icr.modal_app.app::fleet --items
proxycheck,chat --replicas 4`, then set `FLEET_REPLICAS = 4` in `src/icr/config.py` and
rerun `icr assets`. The results pipeline already reports the other fleet size as a
second data set. The full 4-GPU list costs about $17, which needs the caps in
`src/icr/config.py` raised again (total 52, soft stop 45, fleet 35).

**Recommendation.** Publish with the 2-GPU results. They answer the question the project
asks, and the README says plainly that 4 GPUs could not be had. If you want the 4-GPU
numbers later, try at a weekend or late at night, and treat it as an update to a
finished project, not a blocker.

**Done in the meantime.** The build continues on 2 GPUs and stays inside the original
$35 budget.
