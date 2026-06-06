FROM pytorch/pytorch:2.9.1-cuda12.8-cudnn9-devel

WORKDIR /workspace

RUN apt-get update && apt-get install -y git wget ffmpeg libgl1

RUN git clone https://github.com/KwaiVGI/LivePortrait.git

WORKDIR /workspace/LivePortrait

RUN pip install -r requirements.txt

RUN pip install huggingface_hub runpod

# تحميل الأوزان مباشرة إلى المسار المطلوب
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='KwaiVGI/LivePortrait', local_dir='pretrained_weights')"

COPY handler.py /handler.py

CMD ["python", "-u", "/handler.py"]
