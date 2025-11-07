import io
import logging
import os
import shutil
from pathlib import Path

import pretty_midi
import soundfile as sf
from PIL import Image
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.responses import FileResponse

# 🔹 추가 import (webm → mp3 변환용)
from pydub import AudioSegment

from services.inside.inside_return_featuremap import get_normalized_outputs
from services.piano.audio_to_midi import talking_piano
from services.piano.constants import (
    DEFAULT_MP3_PATH,
    DEFAULT_MIDI_PATH,
    ENV_MP3_PATH,
    ENV_MIDI_PATH
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
mp3_path_env = os.getenv(ENV_MP3_PATH)
midi_path_env = os.getenv(ENV_MIDI_PATH)

MP3_PATH = Path(mp3_path_env) if mp3_path_env else DEFAULT_MP3_PATH
MIDI_PATH = Path(midi_path_env) if midi_path_env else DEFAULT_MIDI_PATH

def _midi_to_mp3_bytes(midi_path: Path, sample_rate: int = 44100) -> bytes:
    """Render a MIDI file to MP3 bytes using pretty_midi + pydub."""
    midi_data = pretty_midi.PrettyMIDI(str(midi_path))
    audio = midi_data.synthesize(fs=sample_rate)
    if audio.size == 0:
        raise ValueError("MIDI 파일에 음표가 없어 변환할 수 없습니다.")

    wav_buffer = io.BytesIO()
    sf.write(wav_buffer, audio, sample_rate, format="WAV")
    wav_buffer.seek(0)

    mp3_buffer = io.BytesIO()
    AudioSegment.from_file(wav_buffer, format="wav").export(mp3_buffer, format="mp3")
    return mp3_buffer.getvalue()


# 변환된 MIDI 파일 조회 API
@app.get("/api/piano/")
def get_MIDI():
    if not MIDI_PATH.exists():
        raise HTTPException(status_code=404, detail="변환된 MIDI가 없습니다.")
    midi_file = MIDI_PATH.open("rb")
    return StreamingResponse(
        midi_file,
        media_type="audio/midi",
        headers={"Content-Disposition": f'attachment; filename=\"{MIDI_PATH.name}\"'},
    )

@app.get("/api/piano/mp3")
def get_converted_mp3():
    """백엔드에 저장된 변환 mp3 파일을 브라우저에서 들을 수 있도록 반환"""
    if not MP3_PATH.exists():
        raise HTTPException(status_code=404, detail="변환된 MP3가 없습니다.")
    
    return FileResponse(
        path=MP3_PATH,
        media_type="audio/mpeg",
        filename=MP3_PATH.name
    )


@app.get("/api/piano/midi_to_mp3")
def get_converted_mp3():
    """백엔드에 저장된 변환된 MIDI 파일 다운로드용"""
    if not MIDI_PATH.exists():
        raise HTTPException(status_code=404, detail="변환된 MIDI가 없습니다.")

    try:
        mp3_bytes = _midi_to_mp3_bytes(MIDI_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # pretty_midi or mp3 export failure
        raise HTTPException(status_code=500, detail="MIDI → MP3 변환 실패") from exc

    mp3_filename = f"{MIDI_PATH.stem}.mp3"
    return StreamingResponse(
        io.BytesIO(mp3_bytes),
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'attachment; filename="{mp3_filename}"'}
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

    # 파일 저장
    contents = await voice.read()
    MP3_PATH.write_bytes(contents)

    # ✅ webm/wav 입력 시 자동으로 mp3로 변환
    try:
        if voice.content_type == "audio/webm":
            print("INFO >> webm → mp3 변환 중...")
            AudioSegment.from_file(MP3_PATH, format="webm").export(MP3_PATH, format="mp3")
        elif voice.content_type == "audio/wav":
            print("INFO >> wav → mp3 변환 중...")
            AudioSegment.from_file(MP3_PATH, format="wav").export(MP3_PATH, format="mp3")
    except Exception as e:
        print("ERROR >> webm/wav 변환 실패:", e)
        raise HTTPException(status_code=500, detail="webm/wav → mp3 변환 실패")

    # ✅ MIDI 변환 실행
    try:
        talking_piano()
    except Exception as e:
        print("ERROR >> talking_piano 실패:", e)
        raise HTTPException(status_code=500, detail=str(e))

    return {"message": "MIDI 변환이 완료되었습니다."}
