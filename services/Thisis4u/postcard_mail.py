import html
import logging
import os
import re
import shutil
import smtplib
import ssl
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Literal, Optional, Tuple

import boto3  # type: ignore[import]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import]
from fastapi import HTTPException
from moviepy import VideoFileClip  # type: ignore[import]
from PIL import Image, ImageSequence
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


logger = logging.getLogger(__name__)

MAX_GIF_BYTES = 1_400_000  # raw GIF bytes before base64 (~1.8MB inline)
MAX_VIDEO_BYTES = 15 * 1024 * 1024  # 15MB
MAX_GIF_DURATION = 6  # seconds
TARGET_GIF_FPS = 10
MAX_MESSAGE_CHARS = 600
CSS_COLOR_PATTERN = re.compile(r"^[#a-zA-Z0-9(),.\s%\-]+$")
POSTCARD_S3_BUCKET_ENV = "POSTCARD_S3_BUCKET"
POSTCARD_S3_REGION_ENV = "POSTCARD_S3_REGION"
POSTCARD_S3_BASE_URL_ENV = "POSTCARD_S3_BASE_URL"
POSTCARD_S3_ACL_ENV = "POSTCARD_S3_ACL"


@dataclass(frozen=True)
class GifPreset:
    width: int
    fps: int
    colors: int
    frame_stride: int = 1


GIF_PRESETS: Tuple[GifPreset, ...] = (
    GifPreset(width=320, fps=10, colors=96),
    GifPreset(width=260, fps=8, colors=72),
    GifPreset(width=200, fps=6, colors=56),
    GifPreset(width=160, fps=5, colors=40),
    GifPreset(width=128, fps=4, colors=32, frame_stride=2),
)

def _safe_background(value: str, fallback: str = "#111827") -> str:
    if not value:
        return fallback
    cleaned = value.strip()
    if len(cleaned) > 80:
        cleaned = cleaned[:80]
    return cleaned if CSS_COLOR_PATTERN.match(cleaned) else fallback


def _video_bytes_to_s3_url(video_bytes: bytes) -> str:
    gif_bytes = _convert_video_to_gif(video_bytes)
    return _upload_gif_to_s3(gif_bytes)


def _optimize_gif_file(path: Path, preset: GifPreset) -> None:
    try:
        with Image.open(path) as original:
            frames = []
            durations = []
            accumulated_duration = 0
            default_duration = original.info.get("duration", 80)

            for index, frame in enumerate(ImageSequence.Iterator(original)):
                frame_duration = frame.info.get("duration", default_duration)
                accumulated_duration += frame_duration

                if preset.frame_stride > 1 and index % preset.frame_stride:
                    continue

                reduced = frame.convert("P", palette=Image.ADAPTIVE, colors=preset.colors).copy()
                frames.append(reduced)
                durations.append(accumulated_duration)
                accumulated_duration = 0

            if accumulated_duration and frames:
                durations[-1] += accumulated_duration

            if not frames:
                return

            frames[0].save(
                path,
                format="GIF",
                save_all=True,
                append_images=frames[1:],
                duration=durations,
                loop=original.info.get("loop", 0),
                optimize=True,
                disposal=2,
            )
    except Exception as exc:  # pragma: no cover - 최적화 실패는 치명적이지 않음
        logger.warning("GIF 최적화 실패: %s", exc)


def _upload_gif_to_s3(gif_bytes: bytes) -> str:
    bucket = os.getenv(POSTCARD_S3_BUCKET_ENV)
    if not bucket:
        raise HTTPException(
            status_code=500,
            detail=f"{POSTCARD_S3_BUCKET_ENV} 환경변수를 설정해주세요.",
        )

    region = os.getenv(POSTCARD_S3_REGION_ENV)
    base_url = os.getenv(POSTCARD_S3_BASE_URL_ENV)
    acl = os.getenv(POSTCARD_S3_ACL_ENV)
    key = f"results/thisis4u/{uuid.uuid4().hex}.gif"

    client_kwargs = {"region_name": region} if region else {}
    client = boto3.client("s3", **client_kwargs)

    put_kwargs = {
        "Bucket": bucket,
        "Key": key,
        "Body": gif_bytes,
        "ContentType": "image/gif",
        "CacheControl": "max-age=31536000, public",
    }
    if acl:
        put_kwargs["ACL"] = acl

    try:
        client.put_object(**put_kwargs)
    except (BotoCoreError, ClientError) as exc:
        logger.exception("S3 업로드 실패: %s", exc)
        raise HTTPException(status_code=502, detail=f"S3 업로드 실패: {exc}") from exc

    if base_url:
        return f"{base_url.rstrip('/')}/{key}"

    if region and region != "us-east-1":
        return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"

    return f"https://{bucket}.s3.amazonaws.com/{key}"


def _convert_video_to_gif(video_bytes: bytes) -> bytes:
    if not video_bytes:
        raise HTTPException(status_code=400, detail="비디오 파일이 비어있습니다.")
    if len(video_bytes) > MAX_VIDEO_BYTES:
        mb = MAX_VIDEO_BYTES // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"비디오는 최대 {mb}MB까지 지원됩니다.")

    work_dir = Path(tempfile.mkdtemp(prefix="postcard-"))
    best_bytes: Optional[bytes] = None

    try:
        input_path = work_dir / "clip.mp4"
        output_path = work_dir / "clip.gif"
        input_path.write_bytes(video_bytes)

        for preset in GIF_PRESETS:
            with VideoFileClip(filename=str(input_path), audio=False) as base_clip:
                clip = base_clip

                duration = clip.duration or 0
                if duration and duration > MAX_GIF_DURATION:
                    clip = clip.subclipped(0, MAX_GIF_DURATION)

                width, _ = clip.size
                target_width = min(width or preset.width, preset.width)
                if width and width > target_width:
                    clip = clip.resized(width=target_width)

                source_fps = clip.fps or TARGET_GIF_FPS
                target_fps = max(1, min(int(source_fps), preset.fps))
                clip = clip.with_fps(target_fps)

                clip.write_gif(
                    str(output_path),
                    fps=target_fps,
                )

            _optimize_gif_file(output_path, preset)

            if not output_path.exists():
                raise HTTPException(status_code=500, detail="GIF 파일을 생성하지 못했습니다.")

            gif_bytes = output_path.read_bytes()
            size_kb = len(gif_bytes) / 1024
            logger.info(
                "GIF preset %sx%s colors=%s stride=%s -> %.1fKB",
                preset.width,
                preset.fps,
                preset.colors,
                preset.frame_stride,
                size_kb,
            )

            if best_bytes is None or len(gif_bytes) < len(best_bytes):
                best_bytes = gif_bytes

            if len(gif_bytes) <= MAX_GIF_BYTES:
                return gif_bytes

        assert best_bytes is not None
        logger.warning(
            "최솟값 프리셋으로도 GIF가 %.1fMB입니다. 업로드 영상을 더 축소하세요.",
            len(best_bytes) / (1024 * 1024),
        )
        return best_bytes
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("영상 GIF 변환 실패: %s", exc)
        raise HTTPException(status_code=500, detail=f"GIF 변환 중 오류가 발생했습니다: {exc}") from exc
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


class SendPostcardRequest(BaseModel):
    template_id: Literal["this-is-for-u"] = Field(alias="templateId")
    template_name: Literal["Th!s !s for u"] = Field(alias="templateName")
    created_at: datetime = Field(alias="createdAt")
    front_background: str = Field(alias="frontBackground")
    recipient: EmailStr
    sender: str
    message: str
    front_gif_url: str = Field(alias="frontGifUrl")
    back_gif_url: str = Field(alias="backGifUrl")

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    @field_validator("front_background")
    @classmethod
    def validate_background(cls, value: str) -> str:
        return _safe_background(value)

    @field_validator("sender")
    @classmethod
    def validate_sender(cls, value: str) -> str:
        if not value:
            raise ValueError("sender는 필수입니다.")
        clean = value.strip()
        return clean[:80]

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        if not value:
            raise ValueError("message는 필수입니다.")
        if len(value) > MAX_MESSAGE_CHARS:
            raise ValueError(f"message는 {MAX_MESSAGE_CHARS}자 이하로 입력해주세요.")
        return value

    @classmethod
    def from_form(
        cls,
        *,
        template_id: str,
        template_name: str,
        created_at: datetime,
        front_background: str,
        recipient: str,
        sender: str,
        message: str,
        front_video: bytes,
        back_video: bytes,
    ) -> "SendPostcardRequest":
        front_url = _video_bytes_to_s3_url(front_video)
        back_url = _video_bytes_to_s3_url(back_video)
        return cls(
            templateId=template_id,
            templateName=template_name,
            createdAt=created_at,
            frontBackground=front_background,
            recipient=recipient,
            sender=sender,
            message=message,
            frontGifUrl=front_url,
            backGifUrl=back_url,
        )

    @property
    def recipient_handle(self) -> str:
        return str(self.recipient).split("@", 1)[0]

    def message_preview(self) -> str:
        return self.message if len(self.message) <= 140 else f"{self.message[:137]}..."


def _build_text_body(payload: SendPostcardRequest) -> str:
    return "\n".join(
        [
            f"Postcard for {payload.recipient}",
            f"Template: {payload.template_id} ({payload.template_name})",
            f"Created at: {payload.created_at.isoformat()}",
            f"Front background: {payload.front_background}",
            f"To: {payload.recipient_handle}",
            f"From: {payload.sender}",
            "",
            "Message:",
            payload.message,
        ]
    )


def _build_html_body(payload: SendPostcardRequest) -> str:
    message_html = html.escape(payload.message).replace("\n", "<br>")
    sender_html = html.escape(payload.sender)
    recipient_html = html.escape(payload.recipient_handle)
    date_str = payload.created_at.strftime("%Y / %m / %d")

    return f"""
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#0f172a;font-family:'Pretendard','Apple SD Gothic Neo',Arial,sans-serif;color:#0f172a;">
    <table role="presentation" style="width:100%;border-collapse:collapse;padding:40px 0;">
      <tr>
        <td align="center">
          <div style="width:100%;max-width:640px;margin:0 auto;">
            
            <!-- FRONT CARD -->
            <div style="background-color:{payload.front_background}; border-radius:4px; padding:20px; margin-bottom:40px; box-shadow:0 10px 15px -3px rgba(0,0,0,0.1);">
                <img src="{payload.front_gif_url}" alt="Front" style="width:100%; height:auto; display:block; border-radius:2px; margin:0 auto;" />
            </div>

            <!-- BACK CARD (POSTCARD STYLE) -->
            <div style="background-color:#ffffff; border-radius:4px; padding:40px; box-shadow:0 10px 15px -3px rgba(0,0,0,0.1);">
                <!-- Header -->
                <div style="text-align:center; margin-bottom:30px;">
                    <h2 style="margin:0; font-family:'Times New Roman', serif; font-size:24px; letter-spacing:4px; color:#333; font-weight:normal;">POSTCARD</h2>
                </div>

                <table role="presentation" style="width:100%; border-collapse:collapse;">
                    <tr>
                        <!-- LEFT COLUMN (Message) -->
                        <td style="width:50%; vertical-align:top; padding-right:24px; border-right:1px solid #e2e8f0;">
                            <p style="margin:0 0 24px 0; font-size:18px; font-weight:bold; font-family:'Times New Roman', serif; font-style:italic; color:#1e293b;">
                                To. <span style="font-family:'Pretendard','Apple SD Gothic Neo',Arial,sans-serif; font-style:normal;">{recipient_html}</span>
                            </p>
                            <div style="font-size:15px; line-height:1.8; color:#475569; white-space:pre-wrap; font-family:'Pretendard','Apple SD Gothic Neo',Arial,sans-serif;">{message_html}</div>
                        </td>

                        <!-- RIGHT COLUMN (Meta) -->
                        <td style="width:50%; vertical-align:top; padding-left:24px;">
                            <!-- Date -->
                            <div style="text-align:right; margin-bottom:20px; font-size:13px; color:#94a3b8; font-family:'Times New Roman', serif;">
                                DATE <span style="border-bottom:1px solid #cbd5e1; padding:0 8px; margin-left:4px; font-family:monospace;">{date_str}</span>
                            </div>

                            <!-- Stamp Area -->
                            <div style="text-align:right; margin-bottom:60px;">
                                <div style="display:inline-block; width:90px; height:100px; border:1px dashed #cbd5e1; padding:4px; background:#f8fafc;">
                                    <img src="{payload.back_gif_url}" alt="Stamp" style="width:100%; height:100%; object-fit:contain;" />
                                </div>
                            </div>

                            <!-- Sender -->
                            <div style="text-align:right;">
                                <p style="margin:0; font-size:18px; font-weight:bold; font-family:'Times New Roman', serif; font-style:italic; color:#1e293b;">
                                    From. <span style="font-family:'Pretendard','Apple SD Gothic Neo',Arial,sans-serif; font-style:normal;">{sender_html}</span>
                                </p>
                            </div>
                        </td>
                    </tr>
                </table>
            </div>

            <p style="margin-top:30px; text-align:center; color:#64748b; font-size:12px;">Sent via Th!s !s for u</p>
          </div>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def send_email(to_email: str, subject: str, html_body: str, text_body: str = None):
    smtp_server = os.getenv("MAIL_SERVER")
    smtp_port = int(os.getenv("MAIL_PORT", "587"))
    smtp_user = os.getenv("MAIL_USERNAME")
    smtp_pass = os.getenv("MAIL_PASSWORD")
    from_email = os.getenv("MAIL_FROM") or smtp_user
    from_name = os.getenv("MAIL_FROM_NAME") or ""
    use_starttls = _env_bool("MAIL_STARTTLS", True)
    use_ssl_tls = _env_bool("MAIL_SSL_TLS", False)

    if not all([smtp_server, smtp_port, smtp_user, smtp_pass]):
        raise HTTPException(status_code=500, detail="메일 환경변수가 올바르게 설정되지 않았습니다.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["To"] = to_email

    if text_body:
        msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        if use_ssl_tls:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)

        with server:
            if use_starttls and not use_ssl_tls:
                server.starttls(context=ssl.create_default_context())
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_email, [to_email], msg.as_string())
    except Exception as exc:
        print(f"SMTP 전송 실패: {exc}")
        raise HTTPException(status_code=502, detail=f"SMTP 전송 실패: {exc}") from exc

    return True


def send_postcard_email(payload: SendPostcardRequest):
    subject = f"[Postcard] {payload.template_name}"
    text_body = _build_text_body(payload)
    html_body = _build_html_body(payload)

    try:
        send_email(str(payload.recipient), subject, html_body, text_body)
        logger.info("Postcard mail sent to %s", payload.recipient)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("메일 전송 실패: %s", exc)
        raise HTTPException(status_code=502, detail="메일 전송에 실패했습니다.") from exc
