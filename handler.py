# -*- coding: utf-8 -*-
import base64
import subprocess
import sys
import tempfile
import shutil
import os
from pathlib import Path
from urllib.request import urlretrieve

import runpod

WORKDIR = Path("/workspace")
LIVEPORTRAIT_DIR = WORKDIR / "LivePortrait"
EXPECTED_WEIGHT = LIVEPORTRAIT_DIR / "pretrained_weights/liveportrait/base_models/appearance_feature_extractor.pth"

def ensure_weights():
    """تتأكد من وجود الأوزان في المكان الصحيح، وإلا تحاول إصلاح المسار أو تحميلها"""
    if EXPECTED_WEIGHT.exists():
        print("✅ weights already in correct location")
        return True

    print("⚠️ weights not found in expected path. Trying to fix...")

    # البحث في أي مكان تحت pretrained_weights
    base_weights = LIVEPORTRAIT_DIR / "pretrained_weights"
    if base_weights.exists():
        for root, dirs, files in os.walk(base_weights):
            if "appearance_feature_extractor.pth" in files:
                found = Path(root) / "appearance_feature_extractor.pth"
                print(f"✅ found weights at: {found}")
                # إنشاء المجلد المستهدف
                EXPECTED_WEIGHT.parent.mkdir(parents=True, exist_ok=True)
                # نسخ الملف
                shutil.copy2(found, EXPECTED_WEIGHT)
                print(f"✅ copied to {EXPECTED_WEIGHT}")
                return True

    # آخر حل: تحميل الأوزان من HuggingFace مباشرة داخل الحاوية
    print("⚠️ downloading weights from HuggingFace...")
    try:
        subprocess.run(
            ["huggingface-cli", "download", "KwaiVGI/LivePortrait",
             "--local-dir", "/tmp/live_weights"],
            check=True, capture_output=True
        )
        EXPECTED_WEIGHT.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree("/tmp/live_weights", base_weights, dirs_exist_ok=True)
        print("✅ weights downloaded and installed")
        return True
    except Exception as e:
        print(f"❌ failed to download weights: {e}")
        return False

def write_b64(data_b64: str, path: Path):
    if not data_b64:
        raise ValueError("Missing base64 data")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(data_b64))
    if not path.exists() or path.stat().st_size < 100:
        raise RuntimeError(f"Base64 write failed or file too small: {path}")
    return path

def download(url: str, path: Path):
    if not url:
        raise ValueError("Missing URL")
    path.parent.mkdir(parents=True, exist_ok=True)
    urlretrieve(url, str(path))
    if not path.exists() or path.stat().st_size < 100:
        raise RuntimeError(f"Download failed or file too small: {url}")
    return path

def get_input_file(inp, b64_key, url_key, ext_key, default_ext, path_base: Path):
    ext = inp.get(ext_key) or default_ext
    if not ext.startswith("."):
        ext = "." + ext
    path = path_base.with_suffix(ext)

    if inp.get(b64_key):
        return write_b64(inp.get(b64_key), path)

    if inp.get(url_key):
        return download(inp.get(url_key), path)

    raise ValueError(f"Missing {b64_key} or {url_key}")

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
        # أولاً: نتأكد من وجود الأوزان
        if not ensure_weights():
            return {"ok": False, "error": "LivePortrait weights are missing and could not be fixed"}

        inp = event.get("input", {}) or {}

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)

            source_image = get_input_file(
                inp,
                "source_image_b64",
                "source_image_url",
                "source_image_ext",
                ".png",
                td / "source",
            )

            driving_video = get_input_file(
                inp,
                "driving_video_b64",
                "driving_video_url",
                "driving_video_ext",
                ".mp4",
                td / "driving",
            )

            audio_path = None
            if inp.get("audio_b64") or inp.get("audio_url"):
                audio_path = get_input_file(
                    inp,
                    "audio_b64",
                    "audio_url",
                    "audio_ext",
                    ".mp3",
                    td / "audio",
                )

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
