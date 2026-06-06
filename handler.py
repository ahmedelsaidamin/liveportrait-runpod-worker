# -*- coding: utf-8 -*-
import base64
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.request import urlretrieve

import runpod

WORKDIR = Path("/workspace")
LIVEPORTRAIT_DIR = WORKDIR / "LivePortrait"


def download(url: str, path: Path):
    if not url:
        raise ValueError("Missing URL")
    path.parent.mkdir(parents=True, exist_ok=True)
    urlretrieve(url, str(path))
    if not path.exists() or path.stat().st_size < 100:
        raise RuntimeError(f"Download failed or file too small: {url}")
    return path


def find_latest_mp4(folder: Path) -> Path:
    files = list(folder.rglob("*.mp4"))
    if not files:
        raise RuntimeError("LivePortrait did not create any mp4 output")
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def merge_audio(video_path: Path, audio_path: Path, output_path: Path) -> Path:
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return output_path


def run_liveportrait(source_image: Path, driving_video: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    script_candidates = [
        LIVEPORTRAIT_DIR / "inference.py",
        LIVEPORTRAIT_DIR / "src" / "inference.py",
    ]

    script = None
    for s in script_candidates:
        if s.exists():
            script = s
            break

    if script is None:
        raise RuntimeError("Cannot find LivePortrait inference.py")

    cmd = [
        sys.executable,
        str(script),
        "-s", str(source_image),
        "-d", str(driving_video),
        "-o", str(output_dir),
    ]

    subprocess.run(
        cmd,
        cwd=str(LIVEPORTRAIT_DIR),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    return find_latest_mp4(output_dir)


def handler(event):
    try:
        inp = event.get("input", {}) or {}

        source_image_url = inp.get("source_image_url")
        driving_video_url = inp.get("driving_video_url")
        audio_url = inp.get("audio_url")

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            source_image = download(source_image_url, td / "source.png")
            driving_video = download(driving_video_url, td / "driving.mp4")

            audio_path = None
            if audio_url:
                audio_path = download(audio_url, td / "audio.mp3")

            raw_video = run_liveportrait(source_image, driving_video, td / "lp_output")

            final_video = raw_video
            if audio_path:
                final_video = merge_audio(raw_video, audio_path, td / "final_with_audio.mp4")

            data = final_video.read_bytes()
            return {
                "ok": True,
                "filename": "liveportrait_result.mp4",
                "video_base64": base64.b64encode(data).decode("utf-8"),
                "size_bytes": len(data),
            }

    except subprocess.CalledProcessError as e:
        return {
            "ok": False,
            "error": "Command failed",
            "stdout": e.stdout[-2000:] if e.stdout else "",
            "stderr": e.stderr[-3000:] if e.stderr else str(e),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


runpod.serverless.start({"handler": handler})
