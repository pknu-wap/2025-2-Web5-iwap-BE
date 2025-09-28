from PIL import Image
import io
from services.inside_return_featuremap import process_image, feature_maps, fc, get_normalized_outputs

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from typing import List

app = FastAPI()

app.add_middleware(GZipMiddleware, minimum_size=1000)

# 행렬 구조 반환 API
# 각 레이어에 대한 행렬 값 제공
@app.get("/api/inside/")
def get_inside_layers():
    fmap_out, fc_out = get_normalized_outputs()
    return{
        "layers": {**fmap_out, **fc_out}
    }

# 클라이언트로부터 이미지를 업로드 받는 API
# 미완성
@app.post("/api/inside/")
async def upload_inside_image(num_image: UploadFile = File(...)): # I/O 작업은 비동기로 처리
    contents = await num_image.read()  # 업로드된 파일 읽기
    pil_img = Image.open(io.BytesIO(contents))  # 바이트 데이터를 이미지로 변환
    fmap_out, fc_out = process_image(pil_img)
    return{"이렇게하는게": "맞나?"}