from typing import Union

from fastapi import FastAPI, File, UploadFile
from typing import List

app = FastAPI()


@app.get("/api/inside/")
def get_inside_layers():
    return {
        "layers":	
            {
                "conv1" : [1, 64, 112, 112],
                "layer1.0.conv1" : [1, 64, 56, 56],
                "layer1.0.conv2" : [1, 64, 56, 56],
                "layer1.1.conv1" : [1, 64, 56, 56],
                "layer1.1.conv2" : [1, 64, 56, 56],
                "layer2.0.conv1" : [1, 128, 28, 28],
                "layer2.0.conv2" : [1, 128, 28, 28],
                "layer2.0.downsample.0" : [1, 128, 28, 28],
                "layer2.1.conv1" : [1, 128, 28, 28],
                "layer2.1.conv2" : [1, 128, 28, 28],
                "layer3.0.conv1" : [1, 256, 14, 14],
                "layer3.0.conv2" : [1, 256, 14, 14],
                "layer3.0.downsample.0" : [1, 256, 14, 14],
                "layer3.1.conv1" : [1, 256, 14, 14],
                "layer3.1.conv2" : [1, 256, 14, 14],
                "layer4.0.conv1" : [1, 512, 7, 7],
                "layer4.0.conv2" : [1, 512, 7, 7],
                "layer4.0.downsample.0" : [1, 512, 7, 7],
                "layer4.1.conv1" : [1, 512, 7, 7],
                "layer4.1.conv2" : [1, 512, 7, 7],
                "fc" : [1, 10] 
            }   
        }

@app.post("/api/inside/")
def upload_inside_image(num_image: UploadFile):
    return {"filename": num_image.filename}
    