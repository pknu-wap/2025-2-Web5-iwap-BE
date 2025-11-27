import asyncio
import io
import json
import logging
import os
import sys
import uuid
from dataclasses import asdict
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pickle
import pretty_midi
import soundfile as sf
import numpy as np
import torch
from PIL import Image, UnidentifiedImageError
from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
# 🔹 추가 import (webm → mp3 변환용)
from pydub import AudioSegment
from dotenv import load_dotenv
import uvicorn

from pydantic import EmailStr
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
from services.facial.vae import VAE
from services.Thisis4u.postcard_mail import PostcardEmailPayload, send_postcard_email
from starlette.concurrency import run_in_threadpool

load_dotenv()

#----------------------inside----------------------#
def _load_allowed_origins() -> List[str]:
    raw = os.getenv("ALLOWED_ORIGINS")
    if not raw:
        return []

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
logger = logging.getLogger(__name__)

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
@app.get("/api/inside")
def get_inside_layers():
    result = get_normalized_outputs()
    return result

# 이미지 업로드 후 결과 계산 API
@app.post("/api/inside")
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
@app.post("/api/piano")
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
        print(f"ERROR >> 업로드 파일을 mp3로 변환 실패: {e}")
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
        print("ERROR >> SoundFont 파일을 찾을 수 없어 변환에 실패했습니다.")
        raise HTTPException(status_code=500, detail="SoundFont 파일을 찾을 수 없습니다.")
    except ValueError as e:
        print(f"ERROR >> 변환 중 값 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        print(f"ERROR >> 변환 중 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "success",
        "message": "MIDI 변환이 완료되었습니다.",
        "request_id": request_id,
        "mp3Filename": mp3_filename,
        "midiFilename": midi_filename,
    }

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

@app.get("/api/string")
async def get_string_result():
    """
    POST 요청으로 생성된 JSON 결과를 프론트로 반환
    """
    if not LAST_RESULT_PATH.exists():
        raise HTTPException(status_code=404, detail="아직 생성된 스트링 아트가 없습니다.")
    
    # 파일에 저장된 JSON을 읽어서 그대로 반환
    result = json.loads(LAST_RESULT_PATH.read_text(encoding="utf-8"))
    return JSONResponse(content=result)
    
@app.post("/api/string")
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


def _ensure_image_upload(upload: Optional[UploadFile], label: str) -> UploadFile:
    if upload is None:
        raise HTTPException(status_code=400, detail=f"{label} 파일을 첨부해주세요.")
    content_type = (upload.content_type or "").lower()
    if content_type.startswith("image/"):
        return upload
    filename = (upload.filename or "").lower()
    if filename.endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")):
        return upload
    raise HTTPException(status_code=400, detail=f"{label}은(는) 이미지 파일이어야 합니다.")


def _ensure_video_upload(upload: Optional[UploadFile], label: str) -> UploadFile:
    if upload is None:
        raise HTTPException(status_code=400, detail=f"{label} 파일을 첨부해주세요.")
    content_type = (upload.content_type or "").lower()
    if content_type.startswith("video/"):
        return upload
    filename = (upload.filename or "").lower()
    if filename.endswith(".webm"):
        return upload
    if filename.endswith(".mp4"):
        return upload
    raise HTTPException(status_code=400, detail=f"{label}은(는) 비디오 파일이어야 합니다.")


def _detect_video_format(upload: UploadFile) -> str:
    if upload.content_type:
        lowered = upload.content_type.lower()
        if "webm" in lowered:
            return "webm"
    filename = (upload.filename or "").lower()
    if filename.endswith(".webm"):
        return "webm"
    return "mp4"


async def _read_upload_bytes(upload: UploadFile, label: str) -> bytes:
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"{label} 파일이 비어 있습니다.")
    return data


@app.post("/api/postcards/send")
async def send_postcard(
    recipient: EmailStr = Form(...),
    frontCard: UploadFile = File(...),
    backCard: UploadFile = File(...),
    frontVideo: UploadFile = File(...),
    backVideo: UploadFile = File(...),
):
    front_card_file = _ensure_image_upload(frontCard, "frontCard")
    back_card_file = _ensure_image_upload(backCard, "backCard")
    front_video_file = _ensure_video_upload(frontVideo, "frontVideo")
    back_video_file = _ensure_video_upload(backVideo, "backVideo")

    front_card_bytes, back_card_bytes, front_video_bytes, back_video_bytes = await asyncio.gather(
        _read_upload_bytes(front_card_file, "frontCard"),
        _read_upload_bytes(back_card_file, "backCard"),
        _read_upload_bytes(front_video_file, "frontVideo"),
        _read_upload_bytes(back_video_file, "backVideo"),
    )

    builder = partial(
        PostcardEmailPayload.build,
        recipient=str(recipient),
        front_card_image=front_card_bytes,
        back_card_image=back_card_bytes,
        front_video_bytes=front_video_bytes,
        back_video_bytes=back_video_bytes,
        front_video_format=_detect_video_format(front_video_file),
        back_video_format=_detect_video_format(back_video_file),
    )

    payload = await run_in_threadpool(builder)
    await run_in_threadpool(send_postcard_email, payload)
    return {"status": "success", "message": "메일을 전송했습니다."}

#----------------------fac!al----------------------#
FACIAL_DIR = Path(__file__).resolve().parent / "services" / "facial"
VAE_MODEL_PATH = FACIAL_DIR / "vae_model_20.pth"
LATENTS_PATH = FACIAL_DIR / "latents_selected_attrs.pkl"
# Checkpoints saved with module name 'vae' need an alias to our package path
sys.modules.setdefault("vae", sys.modules["services.facial.vae"])

if not VAE_MODEL_PATH.exists():
    raise FileNotFoundError(f"VAE model not found: {VAE_MODEL_PATH}")
if not LATENTS_PATH.exists():
    raise FileNotFoundError(f"Latents pickle not found: {LATENTS_PATH}")

device = 'cuda' if torch.cuda.is_available() else 'cpu'

# -------------------------------
# 1️⃣ VAE 모델 로드
# -------------------------------
torch.serialization.add_safe_globals([VAE])
# CPU 환경에서도 GPU로 저장된 체크포인트를 읽을 수 있도록 map_location 지정
map_location = torch.device(device)
model = torch.load(VAE_MODEL_PATH, map_location=map_location, weights_only=False)
model.to(device)
model.eval()

# -------------------------------
# 2️⃣ pickle 로드
# -------------------------------
with LATENTS_PATH.open("rb") as f:
    data = pickle.load(f)

latents = data["latents"]        # (N, 128)
attrs = data["attrs"]            # (N, 7)
attr_names = data["attr_names"]  # ["Male","Smiling",...]

# -------------------------------
# 3️⃣ 속성별 latent 방향 계산
# -------------------------------
attr_dirs = []
for i in range(attrs.shape[1]):
    idx_pos = attrs[:, i] == 1
    idx_neg = attrs[:, i] == 0
    dir_vec = latents[idx_pos].mean(axis=0) - latents[idx_neg].mean(axis=0)
    attr_dirs.append(dir_vec)
attr_dirs = np.stack(attr_dirs)  # (7, 128)
mean_latent = latents.mean(axis=0)  # 전체 평균 latent

# -------------------------------
# 4️⃣ 얼굴 이미지 생성 (GET)
# -------------------------------
@app.get("/api/facial")
def generate(
    male: float = 0.0,
    smiling: float = 0.0,
    pale_skin: float = 0.0,
    eyeglasses: float = 0.0,
    mustache: float = 0.0,
    wearing_lipstick: float = 0.0,
    young: float = 0.0,
):
    slider_vals = np.array(
        [male, smiling, pale_skin, eyeglasses, mustache, wearing_lipstick, young],
        dtype=np.float32,
    )

    # latent 생성: mean_latent + slider_vals @ attr_dirs
    z = mean_latent + np.dot(slider_vals, attr_dirs)
    z = torch.tensor(z, dtype=torch.float32).unsqueeze(0).to(device)

    with torch.no_grad():
        out = model.decode(z)

    out = out.view(3, 150, 150).clamp(0, 1)
    img_np = (out.permute(1, 2, 0).cpu().numpy() * 255).astype(np.uint8)
    pil = Image.fromarray(img_np)

    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")
