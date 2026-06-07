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
    if EXPECTED_WEIGHT.exists():
        print("✅ weights already in correct location")
        return True
    print("⚠️ weights not found. Trying to fix...")
    base_weights = LIVEPORTRAIT_DIR / "pretrained_weights"
    if base_weights.exists():
        for root, dirs, files in os.walk(base_weights):
            if "appearance_feature_extractor.pth" in files:
                found = Path(root) / "appearance_feature_extractor.pth"
                EXPECTED_WEIGHT.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(found, EXPECTED_WEIGHT)
                return True
    try:
        subprocess.run(
            ["hf", "download", "KwaiVGI/LivePortrait", "--local-dir", "/tmp/live_weights"],
            check=True, capture_output=True
        )
        EXPECTED_WEIGHT.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree("/tmp/live_weights", base_weights, dirs_exist_ok=True)
        return True
    except Exception as e:
        print(f"❌ failed: {e}")
        return False

def write_b64(data_b64: str, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(data_b64))
    return path

def download_url(url: str, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    urlretrieve(url, str(path))
    return path

def get_file(inp, b64_key, url_key, ext_key, default_ext, dest: Path):
    ext = inp.get(ext_key) or default_ext
    if not ext.startswith("."): ext = "." + ext
    dest = dest.with_suffix(ext)
    if inp.get(b64_key):
        return write_b64(inp[b64_key], dest)
    if inp.get(url_key):
        return download_url(inp[url_key], dest)
    raise ValueError(f"Missing {b64_key} or {url_key}")

def get_audio_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe","-v","quiet","-show_entries","format=duration","-of","csv=p=0",str(path)],
        capture_output=True, text=True
    )
    try: return float(r.stdout.strip())
    except: return 0.0

def cut_audio(audio: Path, start: float, duration: float, out: Path) -> Path:
    """قطع جزء من الـ audio."""
    subprocess.run([
        "ffmpeg","-y",
        "-ss", str(start),
        "-t",  str(duration),
        "-i",  str(audio),
        "-c:a","libmp3lame","-q:a","2",
        str(out)
    ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out

def loop_driving(driving: Path, duration: float, out: Path) -> Path:
    """Loop الـ driving video لمدة محددة."""
    subprocess.run([
        "ffmpeg","-y",
        "-stream_loop","-1",
        "-i", str(driving),
        "-t", str(duration),
        "-c:v","libx264","-preset","fast","-crf","23",
        "-an", str(out)
    ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out

def run_liveportrait(source: Path, driving: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    script = None
    for s in [LIVEPORTRAIT_DIR/"inference.py", LIVEPORTRAIT_DIR/"src"/"inference.py"]:
        if s.exists(): script = s; break
    if not script:
        raise RuntimeError("Cannot find LivePortrait inference.py")
    subprocess.run(
        [sys.executable, str(script), "-s", str(source), "-d", str(driving), "-o", str(output_dir)],
        cwd=str(LIVEPORTRAIT_DIR), check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    files = sorted(output_dir.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files: raise RuntimeError("No mp4 output from LivePortrait")
    return files[0]

def merge_audio(video: Path, audio: Path, out: Path) -> Path:
    subprocess.run([
        "ffmpeg","-y","-i",str(video),"-i",str(audio),
        "-map","0:v:0","-map","1:a:0",
        "-c:v","copy","-c:a","aac","-shortest",
        str(out)
    ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out

def handler(event):
    try:
        if not ensure_weights():
            return {"status":"FAILED","error":"weights missing"}

        inp = event.get("input", {}) or {}

        # chunk params (اختياري)
        chunk_start    = float(inp.get("chunk_start", 0))
        chunk_duration = float(inp.get("chunk_duration", 0))  # 0 = الـ audio كله

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)

            source  = get_file(inp, "source_image_b64",  "source_image_url",  "source_image_ext",  ".png", td/"source")
            driving = get_file(inp, "driving_video_b64", "driving_video_url", "driving_video_ext", ".mp4", td/"driving")
            audio   = get_file(inp, "audio_b64",         "audio_url",         "audio_ext",         ".mp3", td/"audio")

            # قطع الـ chunk المطلوب من الـ audio
            if chunk_duration > 0:
                chunk_audio = td / "chunk_audio.mp3"
                cut_audio(audio, chunk_start, chunk_duration, chunk_audio)
                audio = chunk_audio
                target_dur = chunk_duration
            else:
                target_dur = get_audio_duration(audio)

            # Loop الـ driving video بطول الـ chunk
            if target_dur > 0:
                looped_drv = td / "driving_looped.mp4"
                try:
                    loop_driving(driving, target_dur, looped_drv)
                    if looped_drv.exists() and looped_drv.stat().st_size > 100:
                        driving = looped_drv
                except Exception as le:
                    print(f"⚠️ loop failed: {le}")

            # توليد الفيديو
            raw_video = run_liveportrait(source, driving, td/"lp_output")

            # دمج الصوت
            final = merge_audio(raw_video, audio, td/"final.mp4")

            data = final.read_bytes()
            return {
                "status":       "COMPLETED",
                "ok":           True,
                "video_base64": base64.b64encode(data).decode(),
                "chunk_start":  chunk_start,
                "chunk_duration": chunk_duration,
                "size_bytes":   len(data),
            }

    except subprocess.CalledProcessError as e:
        return {"status":"FAILED","error": f"Command failed: {e.stderr[-2000:] if e.stderr else str(e)}"}
    except Exception as e:
        return {"status":"FAILED","error": str(e)}

runpod.serverless.start({"handler": handler})
