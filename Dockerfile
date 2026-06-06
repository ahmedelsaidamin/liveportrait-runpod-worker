FROM pytorch/pytorch:2.9.1-cuda12.8-cudnn9-devel

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
WORKDIR /workspace

RUN apt-get update && apt-get install -y \
    git wget curl ffmpeg libgl1 libglib2.0-0 build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip setuptools wheel

RUN git clone --depth 1 https://github.com/KwaiVGI/LivePortrait.git /workspace/LivePortrait

WORKDIR /workspace/LivePortrait

RUN if [ -f requirements.txt ]; then pip install -r requirements.txt; fi

# تثبيت أداة HuggingFace Hub
RUN pip install -U "huggingface_hub[cli]"

# إنشاء مجلد الأوزان الهدف
RUN mkdir -p /workspace/LivePortrait/pretrained_weights

# تنزيل الأوزان في مجلد مؤقت ثم نسخها إلى المجلد الصحيح
RUN huggingface-cli download KwaiVGI/LivePortrait --local-dir /tmp/liveportrait_weights \
    && cp -r /tmp/liveportrait_weights/* /workspace/LivePortrait/pretrained_weights/ \
    && rm -rf /tmp/liveportrait_weights

# تأكد من وجود الملف المطلوب (فحص أمان)
RUN test -f /workspace/LivePortrait/pretrained_weights/liveportrait/base_models/appearance_feature_extractor.pth \
    && echo "✅ LivePortrait weights installed correctly" \
    || (echo "❌ ERROR: weights not found at expected path" && exit 1)

RUN pip install --no-cache-dir \
    runpod \
    opencv-python-headless \
    imageio imageio-ffmpeg \
    ffmpeg-python \
    numpy scipy tqdm pillow pyyaml requests \
    moviepy==1.0.3

WORKDIR /
COPY handler.py /handler.py

CMD ["python", "-u", "/handler.py"]
