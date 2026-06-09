# -*- coding: utf-8 -*-
"""
Modal replacement for the old RunPod LivePortrait worker.
Source logic copied/adapted from:
https://github.com/ahmedelsaidamin/liveportrait-runpod-worker

Deploy:
    modal deploy modal_from_github_runpod.py

HF/Flask calls:
    modal.Function.from_name("shakir-lp-v3", "generate_video_v2")
"""

import base64
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.request import urlretrieve

import modal

APP_NAME = "shakir-lp-v3"
WORKDIR = Path("/workspace")
LIVEPORTRAIT_DIR = WORKDIR / "LivePortrait"
EXPECTED_WEIGHT = LIVEPORTRAIT_DIR / "pretrained_weights/liveportrait/base_models/appearance_feature_extractor.pth"

app = modal.App(APP_NAME)

# Build image as close as possible to the old RunPod Dockerfile,
# but using Modal's CUDA image instead of a Dockerfile.
image = (
    modal.Image.from_registry(
        "pytorch/pytorch:2.9.1-cuda12.8-cudnn9-devel",
        add_python="3.11",
    )
    .apt_install(
        "git", "wget", "curl", "ffmpeg", "libgl1", "libglib2.0-0", "build-essential"
    )
    .run_commands(
        "pip install --upgrade pip setuptools wheel",
        "cd /workspace && git clone --depth 1 https://github.com/KwaiVGI/LivePortrait.git",
        "cd /workspace/LivePortrait && pip install -r requirements.txt",
        "pip install -U 'huggingface_hub[cli]'",
        # Same weight layout as the RunPod Dockerfile.
        "cd /workspace/LivePortrait && mkdir -p pretrained_weights/liveportrait/base_models && hf download KwaiVGI/LivePortrait --local-dir /tmp/lp_weights && cp -r /tmp/lp_weights/* pretrained_weights/ && rm -rf /tmp/lp_weights",
        "test -f /workspace/LivePortrait/pretrained_weights/liveportrait/base_models/appearance_feature_extractor.pth && echo '✅ weights OK' || (echo '❌ weights missing' && exit 1)",
        "pip install requests numpy pillow opencv-python-headless imageio imageio-ffmpeg ffmpeg-python moviepy==1.0.3 scipy tqdm pyyaml",
    )
)


def ensure_weights() -> bool:
    """Same idea as RunPod handler: verify/fix weights at runtime if needed."""
    if EXPECTED_WEIGHT.exists():
        print("✅ weights already in correct location")
        return True

    print("⚠️ weights not found. Trying to fix...")
    base_weights = LIVEPORTRAIT_DIR / "pretrained_weights"

    if base_weights.exists():
        for root, _dirs, files in os.walk(base_weights):
            if "appearance_feature_extractor.pth" in files:
                found = Path(root) / "appearance_feature_extractor.pth"
                EXPECTED_WEIGHT.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(found, EXPECTED_WEIGHT)
                print(f"✅ copied weight from {found}")
                return True

    try:
        subprocess.run(
            ["hf", "download", "KwaiVGI/LivePortrait", "--local-dir", "/tmp/live_weights"],
            check=True,
            capture_output=True,
            text=True,
        )
        EXPECTED_WEIGHT.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree("/tmp/live_weights", base_weights, dirs_exist_ok=True)
        print("✅ weights downloaded at runtime")
        return EXPECTED_WEIGHT.exists()
    except Exception as e:
        print(f"❌ failed: {e}")
        return False


def write_b64(data_b64: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(data_b64))
    return path


def download_url(url: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    urlretrieve(url, str(path))
    return path


def get_file(inp: dict, b64_key: str, url_key: str, ext_key: str, default_ext: str, dest: Path) -> Path:
    ext = inp.get(ext_key) or default_ext
    if not str(ext).startswith("."):
        ext = "." + str(ext)
    dest = dest.with_suffix(ext)
    if inp.get(b64_key):
        return write_b64(inp[b64_key], dest)
    if inp.get(url_key):
        return download_url(inp[url_key], dest)
    raise ValueError(f"Missing {b64_key} or {url_key}")


def get_audio_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    try:
        return float((r.stdout or "").strip())
    except Exception:
        return 0.0


def cut_audio(audio: Path, start: float, duration: float, out: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-y", "-ss", str(start), "-t", str(duration), "-i", str(audio),
            "-c:a", "libmp3lame", "-q:a", "2", str(out),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return out


def loop_driving(driving: Path, duration: float, out: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(driving), "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-an", str(out),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return out


def run_liveportrait(source: Path, driving: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    script = None
    for s in [LIVEPORTRAIT_DIR / "inference.py", LIVEPORTRAIT_DIR / "src" / "inference.py"]:
        if s.exists():
            script = s
            break
    if not script:
        raise RuntimeError("Cannot find LivePortrait inference.py")

    subprocess.run(
        [sys.executable, str(script), "-s", str(source), "-d", str(driving), "-o", str(output_dir)],
        cwd=str(LIVEPORTRAIT_DIR),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    files = sorted(output_dir.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError("No mp4 output from LivePortrait")
    return files[0]


def merge_audio(video: Path, audio: Path, out: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-shortest", str(out),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return out


def _run_worker_logic(inp: dict) -> dict:
    if not ensure_weights():
        return {"status": "FAILED", "ok": False, "error": "weights missing"}

    chunk_start = float(inp.get("chunk_start", 0) or 0)
    chunk_duration = float(inp.get("chunk_duration", 0) or 0)

    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        source = get_file(inp, "source_image_b64", "source_image_url", "source_image_ext", ".png", td / "source")
        driving = get_file(inp, "driving_video_b64", "driving_video_url", "driving_video_ext", ".mp4", td / "driving")
        audio = get_file(inp, "audio_b64", "audio_url", "audio_ext", ".mp3", td / "audio")

        if chunk_duration > 0:
            chunk_audio = td / "chunk_audio.mp3"
            cut_audio(audio, chunk_start, chunk_duration, chunk_audio)
            audio = chunk_audio
            target_dur = chunk_duration
        else:
            target_dur = get_audio_duration(audio)

        if target_dur > 0:
            looped_drv = td / "driving_looped.mp4"
            try:
                loop_driving(driving, target_dur, looped_drv)
                if looped_drv.exists() and looped_drv.stat().st_size > 100:
                    driving = looped_drv
            except Exception as le:
                print(f"⚠️ loop failed: {le}")

        raw_video = run_liveportrait(source, driving, td / "lp_output")
        final = merge_audio(raw_video, audio, td / "final.mp4")
        data = final.read_bytes()

        return {
            "status": "COMPLETED",
            "ok": True,
            "video_base64": base64.b64encode(data).decode(),
            "chunk_start": chunk_start,
            "chunk_duration": chunk_duration,
            "size_bytes": len(data),
        }


@app.function(image=image, gpu="T4", timeout=1800, memory=8192)
def generate_video_v2(
    source_image_b64: str | None = None,
    source_image_ext: str = "png",
    driving_video_b64: str | None = None,
    driving_video_ext: str = "mp4",
    audio_b64: str | None = None,
    audio_ext: str = "mp3",
    source_image_url: str | None = None,
    driving_video_url: str | None = None,
    audio_url: str | None = None,
    chunk_start: float = 0,
    chunk_duration: float = 0,
):
    """Modal function with the same input/output shape as the RunPod handler, plus direct kwargs."""
    try:
        inp = {
            "source_image_b64": source_image_b64,
            "source_image_ext": source_image_ext,
            "driving_video_b64": driving_video_b64,
            "driving_video_ext": driving_video_ext,
            "audio_b64": audio_b64,
            "audio_ext": audio_ext,
            "source_image_url": source_image_url,
            "driving_video_url": driving_video_url,
            "audio_url": audio_url,
            "chunk_start": chunk_start,
            "chunk_duration": chunk_duration,
        }
        return _run_worker_logic(inp)
    except subprocess.CalledProcessError as e:
        return {
            "status": "FAILED",
            "ok": False,
            "error": f"Command failed: {e.stderr[-2000:] if e.stderr else str(e)}",
        }
    except Exception as e:
        return {"status": "FAILED", "ok": False, "error": str(e)}


@app.function(image=image, gpu="T4", timeout=1800, memory=8192)
def runpod_style_handler(event: dict):
    """Optional compatibility function: accepts {'input': {...}} like RunPod."""
    try:
        inp = event.get("input", {}) if isinstance(event, dict) else {}
        return _run_worker_logic(inp or {})
    except subprocess.CalledProcessError as e:
        return {
            "status": "FAILED",
            "ok": False,
            "error": f"Command failed: {e.stderr[-2000:] if e.stderr else str(e)}",
        }
    except Exception as e:
        return {"status": "FAILED", "ok": False, "error": str(e)}
