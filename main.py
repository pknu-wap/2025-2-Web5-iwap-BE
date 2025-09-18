from typing import Union

from fastapi import FastAPI, File, UploadFile
from typing import List

app = FastAPI()


@app.get("/api/inside/")
def num_pic(layers: List):
    return {"layers": layers}

@app.post("/api/inside/")
def num_pic(num_image: UploadFile):
    return {"filename": num_image.filename}
    