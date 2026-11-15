// "Walk me through it": four short captioned steps in plain language, over the live replay.

const STEPS = [
  {
    title: "1. Every car is one request",
    text: (ctx) =>
      `Each lit car is one real request to an AI model: a question, plus everything the model has to read before it can answer. In this run about ${ctx.rate} of them arrive every second, at the times real traffic arrived in a public trace.`,
    target: (ctx) => part(ctx.left.canvas, 0, 0.3, 0, 1),
  },
  {
    title: "2. Reading the prompt is the slow part",
    text: () =>
      "Before a GPU can write the first word, it has to read the whole prompt. If it has already read the same opening for an earlier request, it keeps that work in a cache and skips it. A rose flash means the GPU reused its cache. A hollow car is still waiting for its first word.",
    target: (ctx) => part(ctx.right.canvas, 0.3, 1, 0, 1),
  },
  {
    title: "3. The router decides who gets what",
    text: () =>
      "Every request passes this switch. A round-robin router just takes turns, so the same conversation lands on a different GPU each time and nothing is reused. The prefix-aware router looks at how the prompt starts and sends it to the GPU that has read it before, unless that GPU is too busy.",
    target: (ctx) => part(ctx.right.canvas, 0.06, 0.32, 0.2, 0.8),
  },
  {
    title: "4. Same GPUs, same traffic, different result",
    text: (ctx) =>
      ctx.result ||
      "Both sides get exactly the same requests at exactly the same times on the same GPUs. Only the router differs. The scoreboard counts what each one did with them.",
    target: () => document.getElementById("scoreboard").getBoundingClientRect(),
  },
];

function part(element, x0, x1, y0, y1) {
  const r = element.getBoundingClientRect();
  return { left: r.left + r.width * x0, top: r.top + r.height * y0, width: r.width * (x1 - x0), height: r.height * (y1 - y0) };
}

export async function start(state, { setView, render }) {
  await setView("split");
  const layer = document.getElementById("tour");
  const summary = state.index.summary;
  const replay = state.panels.left.replay;
  const ctx = {
    left: state.panels.left,
    right: state.panels.right,
    rate: replay.meta.rate_rps ? Math.round(replay.meta.rate_rps) : Math.round(replay.n / replay.duration),
    result: summary && summary.headline ? summary.headline.tour : null,
  };
  let step = 0;
  state.playing = true;

  const close = () => {
    layer.classList.add("hidden-view");
    layer.innerHTML = "";
    window.removeEventListener("resize", place);
    window.removeEventListener("scroll", place);
  };

  function place() {
    const spot = layer.querySelector(".tour-spot");
    if (!spot) return;
    const r = STEPS[step].target(ctx);
    const pad = 6;
    spot.style.left = `${r.left - pad}px`;
    spot.style.top = `${r.top - pad}px`;
    spot.style.width = `${r.width + 2 * pad}px`;
    spot.style.height = `${r.height + 2 * pad}px`;
  }

  function show() {
    const s = STEPS[step];
    layer.classList.remove("hidden-view");
    layer.innerHTML = `
      <div class="tour-spot"></div>
      <div class="tour-card" role="dialog" aria-label="Guided tour">
        <h4>${s.title}</h4>
        <p>${s.text(ctx)}</p>
        <div class="flex items-center justify-between mt-3">
          <span class="text-xs text-muted mono">${step + 1} / ${STEPS.length}</span>
          <span class="flex gap-2">
            <button data-tour="skip" class="nav-btn">Skip</button>
            ${step > 0 ? '<button data-tour="back" class="nav-btn active">Back</button>' : ""}
            <button data-tour="next" class="tour-btn">${step === STEPS.length - 1 ? "Done" : "Next"}</button>
          </span>
        </div>
      </div>`;
    const r = STEPS[step].target(ctx);
    if (r.top < 0 || r.top + r.height > window.innerHeight) {
      window.scrollTo({ top: window.scrollY + r.top - 80 });
    }
    place();
    render();
  }

  layer.onclick = (e) => {
    const action = e.target.dataset.tour;
    if (action === "skip") close();
    if (action === "back") {
      step -= 1;
      show();
    }
    if (action === "next") {
      if (step === STEPS.length - 1) close();
      else {
        step += 1;
        show();
      }
    }
  };
  window.addEventListener("resize", place);
  window.addEventListener("scroll", place, { passive: true });
  show();
}
