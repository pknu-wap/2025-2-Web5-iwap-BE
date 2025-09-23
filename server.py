from PIL import Image
import io
from Inside_return_featuremap import normalization, process_image, feature_maps, transform

from fastapi import FastAPI, File, UploadFile
from typing import List

app = FastAPI()

# 행렬 구조 반환 API
# 각 레이어에 대한 행렬 값 제공
@app.get("/api/inside/")
def get_inside_layers():
    result = {layer_name: list(fmap.shape) for layer_name, fmap in feature_maps.items()}
    return result

# 클라이언트로부터 이미지를 업로드 받는 API
# 미완성
@app.post("/api/inside/")
async def upload_inside_image(num_image: UploadFile = File(...)): # I/O 작업은 비동기로 처리
    contents = await num_image.read()  # 업로드된 파일 읽기
    pil_img = Image.open(io.BytesIO(contents))  # 바이트 데이터를 이미지로 변환
    feature_maps, fc = process_image(pil_img)
    return{"이렇게하는게": "맞나?"}