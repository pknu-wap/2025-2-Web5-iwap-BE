from matplotlib import pyplot as plt
from PIL import Image
import io
 
from Inside_return_featuremap import normalization, fmap
 
from fastapi import FastAPI, File, UploadFile
from typing import List
 
app = FastAPI()
 
# 행렬 구조 반환 API
# 각 레이어에 대한 행렬 값 제공
@app.get("/api/inside/")
def get_inside_layers():
    return {normalization(fmap)}
 
# 클라이언트로부터 이미지를 업로드 받는 API
# 미완성
@app.post("/api/inside/")
async def upload_inside_image(num_image: UploadFile = File(...)): # I/O 작업은 비동기로 처리
    images = await num_image.read() # 이미지 읽기
    pil = Image.open(io.BytesIO(images)) # 바이트 데이터를 이미지로 변환
    return images
