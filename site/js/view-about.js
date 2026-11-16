// Method view: how the numbers were made, the result tables, and the limits.

import { money, percent } from "./format.js";
import { POLICY_COLORS } from "./yard.js";

const REPO = "https://github.com/Charlie-Gzz/inference-control-room";

function range(s, format) {
  if (!s || s.median == null) return "-";
  const spread = s.min === s.max ? "" : ` <span class="text-muted">(${format(s.min)} to ${format(s.max)})</span>`;
  return `${format(s.median)}${spread}${s.wide ? ' <span title="Repeats differ by more than 10%" style="color:var(--warn)">⚠</span>' : ""}`;
}

const sec = (v) => (v < 1 ? `${Math.round(v * 1000)} ms` : `${v.toFixed(2)} s`);
const ms = (v) => `${Math.round(v * 1000)} ms`;
const pct = (v) => percent(v, 1);
const chip = (policy) => `<span class="chip" style="--c:${POLICY_COLORS[policy]}">${policy}</span>`;

function fleetTable(table) {
  const rows = Object.entries(table.policies)
    .map(
      ([policy, t]) => `<tr>
        <td>${chip(policy)}</td><td>${range(t.ttft_p50_s, sec)}</td><td>${range(t.ttft_p95_s, sec)}</td>
        <td>${range(t.itl_p95_s, ms)}</td><td>${range(t.goodput, pct)}</td><td>${range(t.cache_hit_rate, pct)}</td>
        <td>${range(t.imbalance, (v) => v.toFixed(2))}</td></tr>`,
    )
    .join("");
  return `<div class="card p-4 overflow-x-auto">
    <div class="font-semibold">${table.workload === "no-sharing" ? "no-sharing (control: no two prompts share a prefix)" : table.workload}
      <span class="text-muted font-normal">· ${table.rate_rps} req/s on ${table.replicas || 4} GPUs · median of ${Object.values(table.policies)[0].repeats} repeats (min to max)</span></div>
    <table class="w-full text-sm mt-3 about-table"><thead><tr>
      <th>Policy</th><th>TTFT p50</th><th>TTFT p95</th><th>ITL p95</th><th>Within SLO</th><th>Cache hit rate</th><th>Imbalance</th>
    </tr></thead><tbody>${rows}</tbody></table></div>`;
}

function capacityTable(cap) {
  const rows = Object.entries(cap.policies)
    .map(
      ([policy, t]) => `<tr><td>${chip(policy)}</td>
        <td>${t.repeats.map((r) => r.max_rps_at_slo).join(", ")}</td>
        <td>${t.max_rps_at_slo.median}${t.lower_bound ? " or more" : ""}</td>
        <td>${money(t.cost_per_m_output.median)}</td><td>${money(t.cost_per_m_total.median)}</td></tr>`,
    )
    .join("");
  return `<div class="card p-4 overflow-x-auto">
    <div class="font-semibold">Capacity at the SLO <span class="text-muted font-normal">· chat ramp, levels ${cap.rates_rps.join(", ")} req/s</span></div>
    <table class="w-full text-sm mt-3 about-table"><thead><tr>
      <th>Policy</th><th>Max req/s within SLO, per repeat</th><th>Median</th><th>$ per M output tokens</th><th>$ per M tokens incl. prompt</th>
    </tr></thead><tbody>${rows}</tbody></table></div>`;
}

export function render(root, state) {
  const s = state.index.summary || {};
  const slo = s.slo || { ttft_s: 2, itl_s: 0.1 };
  const facts = s.facts || {};
  // Say what was run, not what was planned: the control and the other fleet runs may be missing.
  const fleet = s.fleet || {};
  const rSat = (s.calibration && s.calibration.r_sat) || {};
  const single = rSat.chat && rSat["no-sharing"]
    ? ` On a single GPU it shows what the cache is worth: one replica saturates at ${rSat["no-sharing"]} req/s without shared prefixes, against ${rSat.chat} with them.`
    : "";
  const control = fleet["no-sharing"]
    ? "The no-sharing workload has no shared prefixes at all. Prefix-aware routing has nothing to exploit there, and the table shows what it does anyway."
    : `The no-sharing workload has no shared prefixes at all, so prefix-aware routing has nothing to exploit there. Its fleet run has not been made yet.${single}`;
  const missing = [
    ...["rag", "no-sharing"].filter((w) => !fleet[w]).map((w) => `the ${w} workload`),
    ...(s.autoscale ? [] : ["the autoscaling comparison"]),
  ];
  const planned = (facts.replicas || 4) < 4
    ? `<li>The plan was a 4-GPU fleet. A 4-GPU container could not be had, so every fleet number here is from ${facts.replicas} GPUs. With fewer replicas a cache-blind router is right more often by accident, so the routing effect is probably smaller than on 4.</li>`
    : "";
  const notRun = missing.length
    ? `<li>Not run on the fleet yet: ${missing.join(", ")}. Only the workloads in the tables above were measured.</li>`
    : "";
  const method = [
    ["Open-loop load", "Every request is sent at its scheduled arrival time, whether or not earlier ones have finished. Latency counts from the scheduled time, so a slow system cannot hide its queue."],
    ["Identical traffic", "Within a repeat, every routing policy gets the same requests at the same times (same seed, same arrivals). Caches and the router's table are emptied before each run."],
    ["Real arrival pattern", 'Arrival times come from the <a class="underline" href="https://github.com/HPMLL/BurstGPT">BurstGPT</a> trace of real ChatGPT traffic (CC BY 4.0), rescaled to this fleet\'s capacity.'],
    ["Repeats", "Every comparison runs three times with different seeds (two for the capacity ramp). Tables show the median with the min and max, and flag spreads above 10%."],
    ["A control", control],
    ["Cost at the SLO", "On the same traffic every policy burns the same GPU-seconds, so raw cost per token is identical. Cost differences come from capacity: fleet cost per hour divided by tokens per hour at the highest traffic level that still meets the SLO."],
    ["Measured or modeled", "Latency, cache hits and replica counts are measured. The GPU-seconds saved by autoscaling are modeled and labeled so."],
  ];
  root.innerHTML = `
    <style>.about-table th{font-weight:500;color:var(--muted);text-align:left;padding:6px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
      .about-table td{padding:8px 10px;border-bottom:1px solid var(--line);font-family:"JetBrains Mono",monospace;font-size:12px;white-space:nowrap}
      .about-table td .text-muted{font-size:11px}</style>
    <div class="space-y-5">
      <div>
        <h1 class="text-2xl font-semibold">How these numbers were made</h1>
        <p class="text-muted mt-2 max-w-3xl">Switchyard is a small LLM serving fleet: ${facts.gpu || "4 GPUs"} in one container, one vLLM replica per GPU serving ${facts.model || "Qwen2.5-7B-Instruct"}, with a Go router in front. Every view on this site replays files recorded during real runs. The latency target (SLO) is p95 time to first token of at most ${slo.ttft_s} s and p95 inter-token latency of at most ${Math.round(slo.itl_s * 1000)} ms, with no failed requests.</p>
      </div>
      <div class="grid gap-3 md:grid-cols-2 max-w-5xl">
        ${method.map(([title, text]) => `<div class="card p-4"><div class="font-semibold">${title}</div><p class="text-sm text-muted mt-1 leading-relaxed">${text}</p></div>`).join("")}
      </div>
      ${s.fleet ? `<h2 class="text-xl font-semibold pt-2">Same traffic, three routers</h2>${Object.values(s.fleet).map(fleetTable).join("")}` : ""}
      ${s.capacity ? capacityTable(s.capacity) : ""}
      <div class="card p-4 max-w-5xl">
        <div class="font-semibold">Limits</div>
        <ul class="text-sm text-muted mt-2 space-y-1.5 list-disc pl-5 leading-relaxed">
          ${planned}${notRun}
          <li>One model family (Qwen2.5-7B) and one GPU type for the fleet (NVIDIA L4). Other models and GPUs will shift every number.</li>
          <li>Prompts are synthetic text with controlled lengths and shared prefixes. Arrival times and response lengths come from a real trace; prompt contents do not.</li>
          <li>All the GPUs sit in one container on one machine. There is no network between router and replicas, so router overhead here is a lower bound.</li>
          <li>Output length is forced (the model is told to ignore its stop token) so every policy produces the same tokens. Real traffic stops when the model decides to.</li>
          <li>Runs are minutes long. Hour-scale effects such as cache churn over a day are not measured.</li>
        </ul>
      </div>
      <div class="text-sm text-muted">Code, raw run files and the full write-up: <a class="underline text-ink" href="${REPO}">${REPO.replace("https://", "")}</a>. Models: Qwen2.5 (Apache 2.0). Quality check: GSM8K (MIT). Engine: ${facts.engine || "vLLM"}.</div>
    </div>`;
}
