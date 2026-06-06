import runpod

def handler(event):
    return {"status": "ok", "message": "LivePortrait worker ready"}

runpod.serverless.start({"handler": handler})
