FROM runpod/pytorch:2.4.0-py3.11-cuda12.1.0-devel-ubuntu22.04

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
