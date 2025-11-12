import io
import logging
import os
import uuid
from pathlib import Path

from PIL import Image
from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.responses import FileResponse

# 🔹 추가 import (webm → mp3 변환용)
from pydub import AudioSegment

from services.inside.inside_return_featuremap import get_normalized_outputs
from services.piano.audio_to_midi import talking_piano, midi_to_mp3_bytes
from services.piano.constants import (
    DEFAULT_MP3_DIR,
    DEFAULT_MIDI_DIR,
    DEFAULT_FINAL_MP3_DIR,
    ENV_MP3_PATH,
    ENV_MIDI_PATH,
    SOUNDFONT_PATH,
)

#----------------------inside----------------------#
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://2025-2-web5-iwap-fe-git-6-45bcd4-nayoung-kims-projects-01021d17.vercel.app",
    "https://2025-2-web5-iwap-fe.vercel.app/piano",
    "https://iwap.kro.kr"
]

LOG_FILE = Path.cwd() / "image_processing.log"
logging.basicConfig(filename=str(LOG_FILE), level=logging.INFO)

app = FastAPI()

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
    result = get_normalized_outputs()
    return result

# 이미지 업로드 후 결과 계산 API
@app.post("/api/inside/")
async def upload_inside_image(num_image: UploadFile = File(...)):
    contents = await num_image.read()
    pil_img = Image.open(io.BytesIO(contents))
    result = get_normalized_outputs(pil_img)
    return result


#----------------------piano----------------------#
def _resolve_storage_dir(raw_path, default_dir: Path) -> Path:
    target = Path(raw_path) if raw_path else default_dir
    directory = target if target.suffix == "" else target.parent
    directory.mkdir(parents=True, exist_ok=True)
    return directory

MP3_DIR = _resolve_storage_dir(os.getenv(ENV_MP3_PATH), DEFAULT_MP3_DIR)
MIDI_DIR = _resolve_storage_dir(os.getenv(ENV_MIDI_PATH), DEFAULT_MIDI_DIR)
FINAL_MP3_DIR = _resolve_storage_dir(None, DEFAULT_FINAL_MP3_DIR)


@app.get("/api/piano/mp3")
def get_converted_mp3(request_id: str = Query(..., description="요청 ID")):
    """백엔드에 저장된 변환 mp3 파일을 브라우저에서 들을 수 있도록 반환"""
    if "/" in request_id or "\\" in request_id:
        raise HTTPException(status_code=400, detail="유효하지 않은 요청 ID입니다.")

    request_id += ".mp3"
    target_path = FINAL_MP3_DIR / request_id
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="변환된 MP3가 없습니다.")
    
    return FileResponse(
        path=target_path,
        media_type="audio/mpeg",
        filename=request_id
    )


@app.get("/api/piano/midi")
def get_converted_midi(request_id: str = Query(..., description="요청 ID")):
    """백엔드에 저장된 변환된 MIDI 파일 다운로드용"""
    if "/" in request_id or "\\" in request_id:
        raise HTTPException(status_code=400, detail="유효하지 않은 요청 ID입니다.")

    request_id += ".mid"
    target_path = MIDI_DIR / request_id
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="변환된 MIDI가 없습니다.")
    
    return FileResponse(
        path=target_path,
        media_type="audio/midi",
        filename=request_id
    )


#----------------------녹음 파일 업로드 및 변환----------------------#
@app.post("/api/piano/")
async def upload_MIDI(voice: UploadFile = File(...)):
    # ✅ webm, wav도 허용하도록 수정
    allowed_types = {"audio/mpeg", "audio/mp3", "audio/webm", "audio/wav"}
    print("DEBUG >> Content-Type:", voice.content_type)

    if voice.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"허용되지 않은 타입입니다: {voice.content_type}",
        )

    request_id = uuid.uuid4().hex
    mp3_filename = f"{request_id}.mp3"
    midi_filename = f"{request_id}.mid"
    final_mp3_filename = f"{request_id}.mp3"

    mp3_path = MP3_DIR / mp3_filename
    midi_path = MIDI_DIR / midi_filename
    final_mp3_path = FINAL_MP3_DIR / final_mp3_filename

    contents = await voice.read()
    format_map = {
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/webm": "webm",
        "audio/wav": "wav",
    }
    try:
        if voice.content_type in {"audio/mpeg", "audio/mp3"}:
            mp3_path.write_bytes(contents)
        else:
            audio_format = format_map.get(voice.content_type)
            if audio_format is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"지원하지 않는 오디오 포맷입니다: {voice.content_type}",
                )
            AudioSegment.from_file(io.BytesIO(contents), format=audio_format).export(
                str(mp3_path), format="mp3"
            )
    except HTTPException:
        raise
    except Exception as e:
        print("ERROR >> 업로드 파일을 mp3로 변환 실패:", e)
        raise HTTPException(status_code=500, detail="업로드 파일을 mp3로 변환하지 못했습니다.")

    # ✅ MIDI 변환 실행
    try:
        midi_obj, sr = talking_piano(mp3_path, midi_path)
    
        if not midi_obj or sr <= 0:
            raise HTTPException(status_code=500, detail="MP3 -> MIDI 변환에 실패했습니다.")

        mp3_bytes = midi_to_mp3_bytes(midi_obj, SOUNDFONT_PATH, sample_rate=sr)
        final_mp3_path.write_bytes(mp3_bytes)

        print(f"\n성공! 최종 MP3 파일이 저장되었습니다: {final_mp3_path}")
        print(f"파일 크기: {len(mp3_bytes) / 1024:.2f} KB")

    except HTTPException:
        raise
    except FileNotFoundError:
        print("SoundFont 파일을 찾을 수 없어 변환에 실패했습니다.")
        raise HTTPException(status_code=500, detail="SoundFont 파일을 찾을 수 없습니다.")
    except ValueError as e:
        print(f"변환 중 값 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        print("ERROR >> talking_piano 또는 MP3 변환 실패:", e)
        raise HTTPException(status_code=500, detail="MIDI 변환 중 오류가 발생했습니다.")

    return {
        "message": "MIDI 변환이 완료되었습니다.",
        "mp3Filename": final_mp3_filename,
        "midiFilename": midi_filename,
        "requestId": request_id,
    }
