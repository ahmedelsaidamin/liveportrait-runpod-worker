# LivePortrait RunPod Worker

المسار المتفق عليه:
LivePortrait + Driving Video + RunPod Serverless

## الملفات
- Dockerfile
- handler.py
- requirements.txt

## ماذا يفعل؟
يستقبل:
- source_image_url: صورة شاكر أو ليان
- driving_video_url: فيديو حركة شخص يتكلم ويتحرك
- audio_url: ملف الصوت النهائي

ثم يشغل LivePortrait ويرجع MP4 بصيغة Base64.

## التشغيل على RunPod
1. ارفع هذه الملفات على GitHub Repository جديد.
2. في RunPod افتح Serverless.
3. اختار Custom deployment.
4. اختار Deploy from GitHub.
5. اختار الريبو.
6. الإعدادات:
   - Endpoint type: Queue
   - Worker type: GPU
   - GPU: 24GB أو 32GB
   - Container disk: 30GB

بعد البناء، RunPod سيعطيك Endpoint ID.

رابط الطلب عادة:
https://api.runpod.ai/v2/YOUR_ENDPOINT_ID/run

ضعه في Hugging Face Secrets باسم:
AVATAR_MOTION_WORKER_URL

وضع مفتاح RunPod باسم:
RUNPOD_API_KEY

## شكل الطلب
{
  "input": {
    "source_image_url": "https://...",
    "driving_video_url": "https://...",
    "audio_url": "https://..."
  }
}

ملاحظة: لو فشل بسبب أوزان LivePortrait، سنأخذ رسالة الخطأ من Logs ونضيف خطوة تنزيل weights.
