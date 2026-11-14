// Loading the index and the replay files (each run is fetched once and cached).

import { Replay } from "./replay.js";

const cache = new Map();
let index = null;

export async function getJSON(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

export async function loadIndex() {
  index = index || (await getJSON("data/index.json"));
  return index;
}

export function loadRun(id) {
  if (!cache.has(id)) {
    const entry = index.runs.find((r) => r.id === id);
    cache.set(id, getJSON(`data/${entry.file}`).then((data) => new Replay(data)));
  }
  return cache.get(id);
}
