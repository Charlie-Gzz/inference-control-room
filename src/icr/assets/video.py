"""Frame-by-frame video capture of the control room's record mode, encoded with ffmpeg.

1. `capture`: the site runs in record mode (`?record=1&story=<name>`). For every frame the
   page is told the frame number, draws it, and a screenshot is saved. No wall clock is
   involved, so the video is reproducible frame for frame.
2. `encode`: ffmpeg (in Docker, so nothing is installed on the host) turns the frames into
   a full-quality master (gitignored) and a web version under 10 MB (committed).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from icr import config, siteserver

VIDEO_DIR = config.ROOT / "assets" / "video"
FRAMES_DIR = VIDEO_DIR / "frames"  # gitignored
MASTERS_DIR = VIDEO_DIR / "masters"  # gitignored
FFMPEG_IMAGE = "jrottenberg/ffmpeg:7.1-alpine"
LABEL = "project=inference-control-room"
PORT = 8798
MAX_WEB_BYTES = 10 * 1024 * 1024


def capture(story: str, mock: bool = False, max_frames: int | None = None) -> dict:
    """Save every frame of a story as PNG. Returns fps, frame count and the frames folder."""
    from playwright.sync_api import sync_playwright

    out = FRAMES_DIR / story
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    server = siteserver.serve_in_thread(PORT, mock=mock)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            # The story file knows its own frame size: read it before opening the page.
            probe = browser.new_page()
            probe.goto(f"http://127.0.0.1:{PORT}/data/{story}.json")
            size = probe.evaluate("JSON.parse(document.body.innerText)")
            probe.close()
            page = browser.new_page(viewport={"width": size["width"], "height": size["height"]})
            page.goto(f"http://127.0.0.1:{PORT}/?record=1&story={story}")
            page.wait_for_function(
                "window.switchyard && window.switchyard.frames > 0", timeout=60000
            )
            info = page.evaluate("({fps: switchyard.fps, frames: switchyard.frames})")
            frames = min(info["frames"], max_frames or info["frames"])
            for frame in range(frames):
                page.evaluate(f"switchyard.seek({frame})")
                page.screenshot(path=str(out / f"{frame:05d}.png"))
            browser.close()
    finally:
        siteserver.stop(server)
    return {"fps": info["fps"], "frames": frames, "dir": out,
            "width": size["width"], "height": size["height"]}  # fmt: skip


def _ffmpeg(args: list[str]) -> None:
    """Run ffmpeg in Docker with assets/video mounted at /video."""
    cmd = ["docker", "run", "--rm", "--label", LABEL, "-v", f"{VIDEO_DIR}:/video", FFMPEG_IMAGE,
           "-hide_banner", "-loglevel", "error", "-y", *args]  # fmt: skip
    subprocess.run(cmd, check=True)


def encode(story: str, fps: int) -> dict[str, Path]:
    """Master (near lossless) and a web MP4 under 10 MB. Returns the written paths."""
    MASTERS_DIR.mkdir(parents=True, exist_ok=True)
    frames = f"/video/frames/{story}/%05d.png"
    master = MASTERS_DIR / f"{story}.mp4"
    x264 = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "slow"]
    _ffmpeg(["-framerate", str(fps), "-i", frames, *x264, "-crf", "14",
             f"/video/masters/{story}.mp4"])  # fmt: skip
    web = VIDEO_DIR / f"{story}.mp4"
    for crf in (23, 26, 29, 32):  # raise compression until the file fits
        _ffmpeg(["-i", f"/video/masters/{story}.mp4", *x264, "-crf", str(crf), "-movflags",
                 "+faststart", f"/video/{story}.mp4"])  # fmt: skip
        if web.stat().st_size <= MAX_WEB_BYTES:
            break
    return {"master": master, "web": web}


def gif(story: str, name: str = "hero") -> Path:
    """README GIF from a story's master: palette-based, scaled down until under 10 MB."""
    out = VIDEO_DIR / f"{name}.gif"
    for width, rate in ((960, 15), (840, 12), (720, 12), (640, 10)):
        filters = (
            f"fps={rate},scale={width}:-1:flags=lanczos,split[a][b];"
            "[a]palettegen=max_colors=160:stats_mode=diff[p];"
            "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle"
        )
        _ffmpeg(["-i", f"/video/masters/{story}.mp4", "-filter_complex", filters,
                 f"/video/{name}.gif"])  # fmt: skip
        if out.stat().st_size <= MAX_WEB_BYTES:
            break
    return out


def make(story: str, mock: bool = False, max_frames: int | None = None) -> dict:
    info = capture(story, mock=mock, max_frames=max_frames)
    return {**info, **encode(story, info["fps"])}


# Storyboard name -> committed file name (assets/video/<name>.mp4).
STORIES = {
    "story-main": "switchyard",
    "story-loop": "switchyard-loop",
    "story-vertical": "switchyard-vertical",
}


def make_all() -> dict[str, Path]:
    """Every video and the README GIF. Masters stay in the gitignored masters folder."""
    written = {}
    for story, name in STORIES.items():
        result = make(story)
        target = VIDEO_DIR / f"{name}.mp4"
        result["web"].replace(target)
        written[name] = target
    written["hero.gif"] = gif("story-loop")
    return written
