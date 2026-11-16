# Demo script (2 minutes)

A shot list and narration for recording your own walkthrough of the control room.
Numbers are the measured ones from `results/RESULTS.md`. If the results change, rerun
`uv run icr assets` and update the lines marked with a number.

## Setup

- `uv run icr site`, then open `http://127.0.0.1:8765` in a clean browser window at
  1920x1080. Hide bookmarks and other tabs.
- Set the speed to 2x. Scrub to about 01:15, just after the warmup ends.
- Record the browser window only. Nothing else on screen.

## Shots

| # | Time | On screen | Say |
|---|---|---|---|
| 1 | 0:00 to 0:12 | Home page, split view playing. Do not touch anything. | "This is Switchyard. Every dot is a real request from a recorded run on two GPUs. Left and right get exactly the same traffic. Only the router is different." |
| 2 | 0:12 to 0:30 | Hover a switch on the left side, then one on the right, so the routing reason shows. | "On the left, round-robin. Each GPU takes its turn, so a follow-up question often lands on a GPU that never saw the conversation and has to read the whole prompt again. On the right, the router remembers where each conversation went and sends it back there." |
| 3 | 0:30 to 0:48 | Point at the middle panel: cache share and time to first token. | "That one change lifts the share of the prompt served from cache from 74% to 84%. The slowest responses start in 0.30 seconds, not 0.51. That is 41% faster on the same hardware." |
| 4 | 0:48 to 1:02 | Click a request on the right. The inspector opens. | "Nothing here is simulated. Click any request and you get its real record: when it was scheduled, which GPU it went to and why, how many tokens came from cache, and how long it took." |
| 5 | 1:02 to 1:22 | Method tab, scroll to the capacity table. | "Faster is nice, but cost is the point. I ramped the traffic until each router broke the latency target. Prefix-aware routing carried 20% more traffic on the same two GPUs. That is 14% lower cost per million tokens." |
| 6 | 1:22 to 1:42 | What-if tab. Drag the inter-token slider from 300 ms down to 100 ms. | "Before the fleet, I measured ten server setups on one GPU: quantization, speculative decoding, batch limits. This picks the cheapest one for any latency target. The plain 4-bit model with prefix caching won. Speculative decoding made it slower." |
| 7 | 1:42 to 2:00 | Back to the split view, playing. | "The load is open-loop, every router sees identical traffic, runs are repeated, and the method was fixed before the results. The whole project cost under ten dollars of GPU time. Code and raw runs are on GitHub." |

Shot 7's cost line: check `docs/GPU_LEDGER.md` for the final total before recording.

## Tips

- Pause half a second before each click. It reads better on video.
- Shot 3 is the one people remember. Slow down there.
- If you run long, cut shot 6.

## Music for the generated video

`uv run icr assets --video` writes three silent videos into `assets/video/`:
`switchyard.mp4` (the main story, about 85 seconds), `switchyard-loop.mp4` (20 seconds)
and `switchyard-vertical.mp4` (1080x1920, for LinkedIn). It also writes `hero.gif` for
the README. Full-quality masters go to `assets/video/masters/`, which is not committed.
To add a royalty-free track to the main story:

- Start the track at 0:00 at low volume under the cold open.
- Bring it up at the zoom out (0:08).
- Drop it to almost nothing at the rewind (about 0:35), then back in on the split view.
- Let it ring out over the end card.

Pick a track whose license allows reuse on LinkedIn and GitHub, and credit it in the
post.
