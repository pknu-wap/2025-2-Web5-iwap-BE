import base64
import html
import logging
import os
import re
import shutil
import smtplib
import ssl
import tempfile
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Literal, Optional, Tuple

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


def _video_bytes_to_data_uri(video_bytes: bytes) -> str:
    gif_bytes = _convert_video_to_gif(video_bytes)
    encoded = base64.b64encode(gif_bytes).decode("ascii")
    return f"data:image/gif;base64,{encoded}"


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
                    clip = clip.subclip(0, MAX_GIF_DURATION)

                width, _ = clip.size
                target_width = min(width or preset.width, preset.width)
                if width and width > target_width:
                    clip = clip.with_size(width=target_width)

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
    front_gif_data_uri: str = Field(alias="frontGifDataUri")
    back_gif_data_uri: str = Field(alias="backGifDataUri")

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
        front_uri = _video_bytes_to_data_uri(front_video)
        back_uri = _video_bytes_to_data_uri(back_video)
        return cls(
            templateId=template_id,
            templateName=template_name,
            createdAt=created_at,
            frontBackground=front_background,
            recipient=recipient,
            sender=sender,
            message=message,
            frontGifDataUri=front_uri,
            backGifDataUri=back_uri,
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

    return f"""
<!doctype html>
<html>
  <body style="margin:0;padding:24px;background:#f7f8fa;font-family:'Pretendard','Apple SD Gothic Neo',Arial,sans-serif;color:#1f2933;">
    <table role="presentation" style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:16px;padding:24px;border:1px solid #e5e7eb;box-shadow:0 10px 35px rgba(15,23,42,0.1);">
      <tr>
        <td>
          <h2 style="margin:0 0 8px 0;color:#0f172a;">Postcard for {payload.recipient}</h2>
          <p style="margin:0 0 16px 0;color:#475569;font-size:14px;">Template · {payload.template_name} ({payload.template_id}) · {payload.created_at.isoformat()}</p>

          <div style="display:flex;flex-wrap:wrap;gap:16px;margin-bottom:16px;">
            <div style="flex:1;min-width:260px;">
              <p style="margin:0 0 8px 0;font-weight:600;color:#0f172a;">Front</p>
              <div style="border-radius:14px;overflow:hidden;border:1px solid rgba(15,23,42,0.08);background:{payload.front_background};padding:16px;display:flex;justify-content:center;align-items:center;min-height:240px;">
                <img src="{payload.front_gif_data_uri}" alt="Front animation" style="max-width:100%;border-radius:12px;display:block;"/>
              </div>
            </div>
            <div style="flex:1;min-width:260px;">
              <p style="margin:0 0 8px 0;font-weight:600;color:#0f172a;">Back</p>
              <div style="border-radius:14px;border:1px solid rgba(15,23,42,0.08);background:#fff;min-height:240px;padding:16px;display:flex;flex-direction:column;gap:12px;">
                <p style="margin:0;font-size:14px;color:#475569;">To. <strong>{html.escape(payload.recipient_handle)}</strong></p>
                <div style="border-radius:12px;overflow:hidden;border:1px dashed rgba(15,23,42,0.12);background:#f8fafc;padding:12px;display:flex;justify-content:center;align-items:center;">
                  <img src="{payload.back_gif_data_uri}" alt="Back animation" style="max-width:100%;display:block;"/>
                </div>
                <div style="font-size:14px;line-height:1.6;color:#1e293b;border-radius:12px;background:#fdf2f8;padding:12px;min-height:80px;">
                  {message_html}
                </div>
                <p style="margin:0;font-size:13px;color:#94a3b8;text-align:right;">from. <strong style="color:#0f172a;">{sender_html}</strong></p>
              </div>
            </div>
          </div>

          <p style="margin:0;font-size:12px;color:#94a3b8;">Sent via Th!s !s for u · {payload.created_at.isoformat()}</p>
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

    print(msg["From"])
    print(msg["To"])
    print(msg["Subject"])

    if text_body:
        msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        if use_ssl_tls:
            print("using ssl")
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15)
        else:
            print("using starttls")
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)

        server.set_debuglevel(1)

        with server:
            if use_starttls and not use_ssl_tls:
                print("starting tls")
                server.starttls(context=ssl.create_default_context())
            print("logging in")
            server.login(smtp_user, smtp_pass)
            print("sending mail")
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

