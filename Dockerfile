FROM nvidia/cuda:12.8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
WORKDIR /workspace

RUN apt-get update && apt-get install -y \
    python3.11 python3-pip git wget curl ffmpeg libgl1 libglib2.0-0 build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --upgrade pip setuptools wheel

# تثبيت PyTorch nightly الذي يدعم sm_120 (RTX 5090)
RUN pip3 install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128

RUN git clone --depth 1 https://github.com/KwaiVGI/LivePortrait.git /workspace/LivePortrait

WORKDIR /workspace/LivePortrait

RUN if [ -f requirements.txt ]; then pip3 install -r requirements.txt; fi

# تثبيت huggingface hub
RUN pip3 install -U "huggingface_hub[cli]"

# إنشاء مجلد الأوزان وتحميلها
RUN mkdir -p /workspace/LivePortrait/pretrained_weights/liveportrait/base_models
RUN huggingface-cli download KwaiVGI/LivePortrait --local-dir /tmp/liveportrait_weights \
    && cp -r /tmp/liveportrait_weights/* /workspace/LivePortrait/pretrained_weights/ \
    && rm -rf /tmp/liveportrait_weights

# تأكيد وجود الوزن المهم
RUN test -f /workspace/LivePortrait/pretrained_weights/liveportrait/base_models/appearance_feature_extractor.pth \
    && echo "✅ weights OK" || (echo "❌ weights missing" && exit 1)

RUN pip3 install --no-cache-dir \
    runpod \
    opencv-python-headless \
    imageio imageio-ffmpeg \
    ffmpeg-python \
    numpy scipy tqdm pillow pyyaml requests \
    moviepy

WORKDIR /
COPY handler.py /handler.py

CMD ["python3", "-u", "/handler.py"]
