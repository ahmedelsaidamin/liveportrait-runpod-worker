import runpod
import subprocess
import os

def handler(event):
    print("Received event:", event)
    return {"status": "ok", "message": "Worker is ready"}

runpod.serverless.start({"handler": handler})
