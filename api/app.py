from fastapi import FastAPI, UploadFile, File, HTTPException
from celery.result import AsyncResult
from celery_app import celery
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import base64

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.post("/api/inside")
async def run_inside(num_image: UploadFile = File(...)):
    contents = await num_image.read()
    num_image_b64_str = base64.b64encode(contents).decode("utf-8")
    task = celery.send_task(
        "inside.return_featuremap",
        kwargs={"num_image_b64_str": num_image_b64_str},
        queue="inside.q",
        routing_key="inside.return_featuremap",
    )
    return {"task_id": task.id}

@app.get("/api/inside")
async def get_inside_layers(task_id: str):
    res = AsyncResult(task_id, app=celery)
    if res.state == "PENDING":
        return {"state": res.state}
    elif res.failed():
        raise HTTPException(status_code=500, detail=str(res.info))
    else:
        return {"state": res.state, "result": res.result}

# @app.post("/api/piano/")
# async def run_piano(voice: UploadFile = File(...)):
#     task = celery.send_task(
#         "piano.audio_to_MIDI",
#         kwargs={"voice": voice},
#         queue="piano.q",
#         routing_key="piano.audio_to_MIDI",
#     )
#     return {"task_id": task.id}

# @app.get("/api/piano/")
# async def get_piano_status(task_id: str):
#     res = AsyncResult(task_id, app=celery)
#     if res.state == "PENDING":
#         return {"state": res.state}
#     elif res.failed():
#         raise HTTPException(status_code=500, detail=str(res.info))
#     else:
#         return {"state": res.state, "result": res.result}
