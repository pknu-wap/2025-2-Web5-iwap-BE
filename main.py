import io
import json
import logging
import os
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pretty_midi
import soundfile as sf
import numpy as np
from PIL import Image, UnidentifiedImageError
from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse

# 🔹 추가 import (webm → mp3 변환용)
from pydub import AudioSegment
from dotenv import load_dotenv

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
from services.string.generate import (
    StringArtOptions,
    StringArtResult,
    generate_string_art_from_array,
)

load_dotenv()

#----------------------inside----------------------#
DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://2025-2-web5-iwap-fe-git-6-45bcd4-nayoung-kims-projects-01021d17.vercel.app",
    "https://2025-2-web5-iwap-fe.vercel.app/piano",
    "https://iwap.kro.kr",
]


def _load_allowed_origins() -> List[str]:
    raw = os.getenv("ALLOWED_ORIGINS")
    if not raw:
        return DEFAULT_ALLOWED_ORIGINS

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(origin).strip() for origin in parsed if str(origin).strip()]
    except json.JSONDecodeError:
        pass

    return [origin.strip() for origin in raw.split(",") if origin.strip()]


ALLOWED_ORIGINS = _load_allowed_origins()

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

    return {"message": "MIDI 변환이 완료되었습니다."}

#----------------------Str!ng----------------------#
LAST_RESULT_PATH = Path.cwd() / "services" / "string" / "last_result.json"
LAST_IMAGE_PATH = LAST_RESULT_PATH.with_suffix(".png")
LAST_RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)

def generate_string_metadata(image_bytes: bytes, options: StringArtOptions) -> Tuple[Dict[str, Any], bytes]:
    image_array = _load_upload_image(image_bytes)
    result = generate_string_art_from_array(image_array, options)
    metadata = _result_to_metadata(result)
    rendered_image = _render_result_image(result)
    return metadata, rendered_image


def _load_upload_image(data: bytes) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(data)) as pil_image:
            pil_image = pil_image.convert("RGB")
            return np.asarray(pil_image, dtype=np.float32)
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=400, detail="유효한 이미지 파일을 업로드해주세요.") from exc


def _result_to_metadata(result: StringArtResult) -> Dict[str, Any]:
    return {
        "mode": result.mode,
        "pullOrders": result.pull_orders,
        "nails": result.nails,
        "scaledNails": result.scaled_nails,
        "settings": asdict(result.options),
    }


def _render_result_image(result: StringArtResult) -> bytes:
    buffer = io.BytesIO()
    image = _array_to_pil_image(result.image, result.mode)
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _array_to_pil_image(array: np.ndarray, mode: str) -> Image.Image:
    clipped = np.clip(array, 0.0, 1.0)
    if mode == "rgb":
        if clipped.ndim == 2:
            clipped = np.stack([clipped] * 3, axis=-1)
        data = (clipped * 255).astype(np.uint8)
        return Image.fromarray(data, "RGB")

    if clipped.ndim == 3:
        clipped = clipped[:, :, 0]
    data = (clipped * 255).astype(np.uint8)
    return Image.fromarray(data, "L")

@app.get("/api/string/")
async def get_string_result():
    """
    POST 요청으로 생성된 JSON 결과를 프론트로 반환
    """
    if not LAST_RESULT_PATH.exists():
        raise HTTPException(status_code=404, detail="아직 생성된 스트링 아트가 없습니다.")
    
    # 파일에 저장된 JSON을 읽어서 그대로 반환
    result = json.loads(LAST_RESULT_PATH.read_text(encoding="utf-8"))
    return JSONResponse(content=result)
    
@app.post("/api/string/")
async def upload_image(
    file: UploadFile = File(...),
    radius: int = Form(50),           # -r (랜덤으로 선택할 못 개수)
    limit: int = Form(5000),          # -l (실행 최대 횟수)
    rgb: bool = Form(True),           # --rgb
    wb: bool = Form(True),            # --wb (배경색 반전)
    nail_step: int = Form(4),         # -n
    strength: float = Form(0.1)  
):
    """
    사용자가 이미지 업로드, 스트링 아트 설정값 보냄 -> 스트링 아트로 변환
    """
    try:
        contents = await file.read()
        options = StringArtOptions(
            side_len=300,
            export_strength=strength,
            pull_amount=limit,
            random_nails=radius,
            nail_step=nail_step,
            wb=wb,
            rgb=rgb,
        )
        metadata, rendered_image = generate_string_metadata(contents, options)

        result_payload = {
            "status": "success",
            "message": "String Art nail 데이터 생성 완료",
            "input_file": file.filename,
            "settings": {
                "radius": radius,
                "limit": limit,
                "rgb": rgb,
                "wb": wb,
                "nail_step": nail_step,
                "strength": strength,
            },
            "mode": metadata["mode"],
            "pullOrders": metadata["pullOrders"],
            "nails": metadata["nails"],
            "scaledNails": metadata["scaledNails"],
        }

        LAST_IMAGE_PATH.write_bytes(rendered_image)

        LAST_RESULT_PATH.write_text(
            json.dumps(result_payload, ensure_ascii=False),
            encoding="utf-8"
        )

        return result_payload
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서버 내부 오류: {e}") from e
    
@app.get("/api/string/image")
async def get_string_image():
    """
    마지막 스트링 아트 결과 이미지를 PNG로 반환
    """
    if not LAST_RESULT_PATH.exists():
        raise HTTPException(status_code=404, detail="아직 생성된 스트링 아트가 없습니다.")
    if not LAST_IMAGE_PATH.exists():
        raise HTTPException(status_code=404, detail="저장된 이미지가 없습니다.")

    image_file = LAST_IMAGE_PATH.open("rb")
    return StreamingResponse(
        image_file,
        media_type="image/png",
        headers={"Content-Disposition": 'inline; filename="string_art.png"'}
    )
