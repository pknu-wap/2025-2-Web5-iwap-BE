from typing import Union

from fastapi import FastAPI, File, UploadFile
from typing import List

app = FastAPI()


@app.get("/api/inside/")
def get_inside_layers():
    return {"layers": ["layer1", "layer2", "layer3"]}

@app.post("/api/inside/")
def upload_inside_image(num_image: UploadFile):
    return {"filename": num_image.filename}
    