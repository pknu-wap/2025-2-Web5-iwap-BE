import io
import logging
import os
from pathlib import Path
import json

from PIL import Image

from services.inside.inside_return_featuremap import get_normalized_outputs
from services.piano.audio_to_MIDI import talking_piano

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

#----------------------inside----------------------#
# 로깅 설정 (플랫폼 독립, 프로젝트 폴더에 기록)
LOG_FILE = os.path.join(os.getcwd(), 'image_processing.log')
logging.basicConfig(filename=LOG_FILE, level=logging.INFO)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 마지막 결과 조회 API
@app.get("/api/inside/")
def get_inside_layers():
    result = get_normalized_outputs()   # pil_image 없이 호출 → last_result 반환
    return result

# 이미지 업로드 후 결과 계산 API
@app.post("/api/inside/")
async def upload_inside_image(num_image: UploadFile = File(...)):
    contents = await num_image.read()
    pil_img = Image.open(io.BytesIO(contents))
    result = get_normalized_outputs(pil_img)   # 새 이미지로 계산
    return result

#----------------------piano----------------------#
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR /"services"/"piano"/"config.json"

with CONFIG_PATH.open("r") as config_file:
    configs = json.load(config_file)

# MP3 및 MIDI 파일 경로 설정
mp3_path = Path(configs["mp3_path"])
if not mp3_path.is_absolute():
    mp3_path = BASE_DIR / mp3_path    
midi_path = Path(configs["output_midi_path"])
if not midi_path.is_absolute():
    midi_path = BASE_DIR / midi_path

# 변환된 MIDI 파일 조회 API
@app.get("/api/piano/")
def get_MIDI():
    if not midi_path.exists():
        raise HTTPException(status_code=404, detail="변환된 MIDI가 없습니다.")

    midi_file = midi_path.open("rb")
    
    return StreamingResponse(
        midi_file,
        media_type="audio/midi",
        headers={"Content-Disposition": f'attachment; filename="{midi_path.name}"'},
    )


# audio 파일 업로드 후 MIDI 변환 API
@app.post("/api/piano/")
async def upload_MIDI(voice: UploadFile = File(...)):
    allowed_types = {"audio/mpeg", "audio/mp3"}
    if voice.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="MP3 파일만 업로드할 수 있습니다.",
    )
    
    contents = await voice.read()
    with open(mp3_path, "wb") as mp3_file:
        mp3_file.write(contents)
    
    talking_piano()   # mp3_path에 저장된 파일로 MIDI 변환
    return {"message": "MIDI 변환이 완료되었습니다."}
