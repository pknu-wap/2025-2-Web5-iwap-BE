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
# CORS: 프론트 개발 도메인(포트) 명시. credentials 사용 시 * 금지
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
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
    # 업로드 허용 타입 확장: mp3, webm, wav
    allowed_types = {"audio/mpeg", "audio/mp3", "audio/webm", "audio/wav"}
    if voice.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="지원하지 않는 오디오 타입입니다.",
    )
    # 저장 파일 확장자 매핑
    ext_by_type = {
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/webm": ".webm",
        "audio/wav": ".wav",
    }

    contents = await voice.read()

    # 입력 저장 경로를 config의 mp3_path 디렉터리를 기준으로 생성
    input_dir = Path(mp3_path).parent
    input_dir.mkdir(parents=True, exist_ok=True)
    input_path = mp3_path

    with open(input_path, "wb") as in_file:
        in_file.write(contents)

    # 업로드된 경로를 사용해 MIDI 변환 수행 (출력 경로도 config와 일치)
    talking_piano()
    return {"message": "MIDI 변환이 완료되었습니다."}
