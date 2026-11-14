// Record mode (?record=1&story=<name>): a deterministic director for frame-by-frame video
// capture. Nothing here uses wall-clock time or CSS animations: every pixel is a function
// of the frame number, so the same storyboard always renders the same video.
//
// The capture script calls `await window.switchyard.seek(frame)` and takes a screenshot.
// The storyboard (data/<story>.json) is generated from the real results by `icr assets`.

import { getJSON, loadRun } from "./data.js";
import { POLICY_COLORS, Yard } from "./yard.js";

const smooth = (u) => (u <= 0 ? 0 : u >= 1 ? 1 : u * u * (3 - 2 * u));
const lerp = (a, b, u) => a + (b - a) * u;
const frameDone = () => new Promise((resolve) => requestAnimationFrame(() => resolve()));

const COLD_SLOWDOWN = 0.45; // replay seconds per video second while following one request
const COLD_LEAD = 1.45; // start this long before the request reaches its GPU

function el(tag, id, parent, html = "") {
  const node = document.createElement(tag);
  node.id = id;
  node.innerHTML = html;
  parent.appendChild(node);
  return node;
}

export async function install(state, api) {
  const name = new URLSearchParams(location.search).get("story") || "story";
  const story = await getJSON(`data/${name}.json`);
  document.body.classList.add("recording");
  if (story.vertical) document.body.classList.add("vertical");
  state.playing = false;

  // Overlay layers, back to front.
  const layer = el("div", "rec-layer", document.body);
  const cineWrap = el("div", "rec-cine", layer, "<canvas></canvas>");
  const cine = new Yard(cineWrap.querySelector("canvas"));
  const badge = el("div", "rec-badge", layer);
  const number = el("div", "rec-number", layer);
  const end = el("div", "rec-end", layer);
  const caption = el("div", "rec-caption", layer);
  const curtain = el("div", "rec-curtain", layer);

  // Scene start times, and every run loaded before the first frame.
  let at = 0;
  const scenes = story.scenes.map((scene) => {
    const placed = { ...scene, start: at };
    at += scene.seconds;
    return placed;
  });
  const ids = new Set();
  for (const s of scenes) {
    if (s.run) ids.add(s.run);
  }
  const replays = Object.fromEntries(await Promise.all([...ids].map(async (id) => [id, await loadRun(id)])));
  const whatif = scenes.some((s) => s.kind === "whatif") ? await import("./view-whatif.js") : null;
  let current = -1;

  async function select(s) {
    state.scenario = s.scenario;
    state.seed = s.seed;
    Object.assign(state.policies, s.policies || {});
    await api.setView(s.view);
  }

  async function enter(s) {
    for (const node of [cineWrap, badge, number, end]) node.style.display = "none";
    cineWrap.style.opacity = "1";
    if (s.kind === "cold" || s.kind === "zoomout") {
      await select(s);
      cineWrap.style.display = "block";
      cine.resize();
      cine.setReplay(replays[s.run], POLICY_COLORS[replays[s.run].meta.policy]);
    } else if (s.kind === "replay" || s.kind === "rewind") {
      await select(s);
      if (s.kind === "rewind") {
        badge.style.display = "block";
        badge.textContent = "◀◀  same traffic, again";
      }
    } else if (s.kind === "number") {
      number.style.display = "flex";
    } else if (s.kind === "whatif") {
      await api.setView("whatif");
    } else if (s.kind === "end") {
      end.style.display = "flex";
      end.innerHTML = `<img src="assets/logo.svg" alt="" width="132" height="132">
        <div class="rec-end-name">Switchyard</div>
        <div class="rec-end-line">${s.line}</div>
        <div class="rec-end-url">${s.url}</div>`;
    }
  }

  function coldTime(s, local) {
    const replay = replays[s.run];
    return replay.req.t[s.request] - COLD_LEAD + local * COLD_SLOWDOWN;
  }

  function update(s, local) {
    const u = local / s.seconds;
    if (s.kind === "cold") {
      const T = coldTime(s, local);
      const [x, y] = cine.carXY(s.request, T);
      const scale = lerp(3.4, 2.5, smooth(u));
      cine.draw(T, { only: s.request, camera: { scale, cx: x / cine.w, cy: y / cine.h } });
      state.T = T;
    } else if (s.kind === "zoomout") {
      // Continue from where the cold open stopped, pull back, and let the traffic in.
      const T0 = coldTime(s, s.cold_seconds);
      const T = T0 + local * lerp(COLD_SLOWDOWN, s.speed, smooth(local / 2.5));
      const pull = smooth(local / (s.seconds * 0.55));
      const [x, y] = cine.carXY(s.request, T);
      const camera = { scale: lerp(2.5, 1, pull), cx: lerp(x / cine.w, 0.5, pull), cy: lerp(y / cine.h, 0.5, pull) };
      cine.draw(T, { camera });
      state.T = T;
      api.render();
      cineWrap.style.opacity = String(1 - smooth((local - (s.seconds - 0.8)) / 0.7));
    } else if (s.kind === "replay") {
      state.T = s.t0 + local * s.speed;
      api.render();
    } else if (s.kind === "rewind") {
      state.T = lerp(s.t_from, s.t_to, smooth(u));
      api.render();
      badge.style.opacity = String(Math.min(1, local / 0.2, (s.seconds - local) / 0.2));
    } else if (s.kind === "number") {
      number.innerHTML = `<div class="rec-number-line">${s.line}</div><div class="rec-number-row">${s.items
        .map((item, k) => {
          const shown = smooth((local - 0.5 - k * 0.55) / 0.9);
          const value = `${item.prefix || ""}${(item.value * shown).toFixed(item.digits || 0)}${item.suffix || ""}`;
          return `<div class="rec-number-item" style="opacity:${shown};transform:translateY(${(1 - shown) * 28}px)">
            <div class="rec-number-value">${value}</div><div class="rec-number-label">${item.label}</div></div>`;
        })
        .join("")}</div><div class="rec-number-foot" style="opacity:${smooth((local - 2.6) / 0.8)}">${s.foot || ""}</div>`;
    } else if (s.kind === "whatif") {
      const move = smooth((local - 1.2) / Math.max(s.seconds - 4.2, 0.5));
      const root = document.getElementById("view-whatif");
      whatif.setTarget(root, state, lerp(s.from.ttft, s.to.ttft, move), lerp(s.from.itl, s.to.itl, move));
    } else if (s.kind === "end") {
      end.style.opacity = String(smooth(local / 0.9));
    }
  }

  // Captions enter word by word and leave together.
  function captions(s, local) {
    const active = (s.captions || []).find((c) => local >= c.at && local < c.at + c.for);
    if (!active) {
      caption.style.opacity = "0";
      caption.innerHTML = "";
      return;
    }
    const t = local - active.at;
    const out = smooth((active.for - t) / 0.35);
    const words = active.text.split(" ");
    caption.style.opacity = String(out);
    caption.className = active.top ? "top" : "";
    caption.innerHTML = `<span class="rec-caption-box">${words
      .map((word, k) => {
        const shown = smooth((t - k * 0.07) / 0.3);
        return `<span style="display:inline-block;opacity:${shown};transform:translateY(${(1 - shown) * 14}px)">${word}&nbsp;</span>`;
      })
      .join("")}</span>`;
  }

  // Fades at scene edges that ask for them ("in", "out" in seconds).
  function fade(s, local) {
    let dark = 0;
    if (s.fade_in) dark = Math.max(dark, 1 - smooth(local / s.fade_in));
    if (s.fade_out) dark = Math.max(dark, 1 - smooth((s.seconds - local) / s.fade_out));
    curtain.style.opacity = String(dark);
  }

  async function seek(frame) {
    const t = Math.min(frame / story.fps, at - 1e-6);
    const k = scenes.findIndex((s) => t >= s.start && t < s.start + s.seconds);
    const scene = scenes[k];
    if (k !== current) {
      current = k;
      await enter(scene);
    }
    const local = t - scene.start;
    update(scene, local);
    captions(scene, local);
    fade(scene, local);
    await frameDone();
    return true;
  }

  window.switchyard = { fps: story.fps, frames: Math.round(at * story.fps), seconds: at, width: story.width, height: story.height, seek };
  await seek(0);
}
