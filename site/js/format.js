// Number formatting and the plain-language reason for a routing decision.

export const CHUNK_TOKENS = 42; // one 256-byte text chunk is about 42 tokens of this text

export function seconds(v) {
  if (v == null || Number.isNaN(v)) return ["-", ""];
  if (v < 0.9995) return [String(Math.round(v * 1000)), "ms"];
  return [v < 10 ? v.toFixed(2) : v.toFixed(1), "s"];
}

export function secondsText(v) {
  const [value, unit] = seconds(v);
  return unit ? `${value} ${unit}` : value;
}

export function percent(v, digits = 0) {
  return v == null ? "-" : `${(v * 100).toFixed(digits)}%`;
}

export function integer(v) {
  return v == null ? "-" : Math.round(v).toLocaleString("en-US");
}

export function compact(v) {
  if (v == null) return "-";
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e4) return `${(v / 1e3).toFixed(0)}k`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}k`;
  return String(Math.round(v));
}

export function clock(t) {
  const s = Math.max(0, Math.floor(t));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export function money(v) {
  return v == null ? "-" : `$${v.toFixed(v < 1 ? 3 : 2)}`;
}

// Why the router picked this GPU, in one or two plain sentences.
export function why(rec) {
  const gpu = `GPU ${rec.replica}`;
  const loads = rec.loads && rec.loads.length ? ` Requests in flight per GPU at that moment: ${rec.loads.join(", ")}.` : "";
  switch (rec.reason) {
    case "prefix-hit":
      return `${gpu} had already served the start of this prompt: ${rec.matched} text chunks matched (about ${integer(rec.matched * CHUNK_TOKENS)} tokens), so its cache could be reused.${loads}`;
    case "prefix-overloaded":
      return `A GPU had this prompt's start cached (${rec.matched} chunks) but was over the load bound, so the request went to the least loaded one, ${gpu}.${loads}`;
    case "no-prefix":
      return `No GPU had seen the start of this prompt, so it went to the least loaded one, ${gpu}.${loads}`;
    case "round-robin":
      return `Round-robin: ${gpu} was next in turn. The prompt was not looked at.${loads}`;
    case "least-loaded":
      return `${gpu} had the fewest requests in flight. The prompt was not looked at.${loads}`;
    default:
      return `Sent straight to ${gpu} (no router).`;
  }
}

export const KIND_LABEL = {
  chat: "chat turn",
  oneoff: "one-off prompt",
  rag: "question over a document",
  agentic: "agent step",
  unique: "unique prompt (control)",
};
