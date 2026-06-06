FROM pytorch/pytorch:2.9.1-cuda12.8-cudnn9-devel

WORKDIR /workspace

RUN apt-get update && apt-get install -y \
    git wget curl ffmpeg libgl1 libglib2.0-0 build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip setuptools wheel

RUN git clone --depth 1 https://github.com/KwaiVGI/LivePortrait.git

WORKDIR /workspace/LivePortrait

RUN pip install -r requirements.txt

RUN pip install -U "huggingface_hub[cli]"

# ✅ الأمر الصحيح باستخدام hf بدلاً من huggingface-cli
RUN mkdir -p pretrained_weights/liveportrait/base_models && \
    hf download KwaiVGI/LivePortrait --local-dir /tmp/lp_weights && \
    cp -r /tmp/lp_weights/* pretrained_weights/ && \
    rm -rf /tmp/lp_weights

RUN test -f pretrained_weights/liveportrait/base_models/appearance_feature_extractor.pth \
    && echo "✅ weights OK" || (echo "❌ weights missing" && exit 1)

RUN pip install runpod opencv-python-headless imageio imageio-ffmpeg \
    ffmpeg-python numpy scipy tqdm pillow pyyaml requests moviepy

WORKDIR /
COPY handler.py /handler.py

CMD ["python", "-u", "/handler.py"]
