import html
import io
import logging
import os
import smtplib
import ssl
import tempfile
import shutil
from dataclasses import dataclass
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional, Tuple

from fastapi import HTTPException
from moviepy import VideoFileClip  # type: ignore[import]
from PIL import Image, ImageSequence
from pydantic import BaseModel, EmailStr, Field


logger = logging.getLogger(__name__)

MAX_VIDEO_BYTES = 15 * 1024 * 1024  # 15MB
MAX_GIF_DURATION = 6  # seconds
TARGET_GIF_FPS = 10
MAX_IMAGE_WIDTH = 1600


@dataclass(frozen=True)
class GifPreset:
    width: int
    fps: int
    colors: int
    frame_stride: int = 1


GIF_PRESETS: Tuple[GifPreset, ...] = (
    GifPreset(width=360, fps=10, colors=96),
    GifPreset(width=300, fps=8, colors=72),
    GifPreset(width=240, fps=6, colors=56),
    GifPreset(width=180, fps=5, colors=40),
    GifPreset(width=140, fps=4, colors=32, frame_stride=2),
)


def _optimize_gif_file(path: Path, preset: GifPreset) -> None:
    try:
        with Image.open(path) as original:
            frames = []
            durations = []
            default_duration = original.info.get("duration", 80)
            carry = 0

            for index, frame in enumerate(ImageSequence.Iterator(original)):
                frame_duration = frame.info.get("duration", default_duration)
                carry += frame_duration

                if preset.frame_stride > 1 and index % preset.frame_stride:
                    continue

                reduced = frame.convert("P", palette=Image.ADAPTIVE, colors=preset.colors).copy()
                frames.append(reduced)
                durations.append(carry)
                carry = 0

            if carry and frames:
                durations[-1] += carry

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
    except Exception as exc:  # pragma: no cover
        logger.warning("GIF 최적화 실패: %s", exc)


def _normalize_image(image_bytes: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(image_bytes)) as raw:
            image = raw.convert("RGB")
            if image.width > MAX_IMAGE_WIDTH:
                ratio = MAX_IMAGE_WIDTH / image.width
                resized_height = max(1, int(image.height * ratio))
                image = image.resize((MAX_IMAGE_WIDTH, resized_height), Image.LANCZOS)

            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            return buffer.getvalue()
    except Exception as exc:
        logger.exception("이미지 처리 실패: %s", exc)
        raise HTTPException(status_code=400, detail="이미지 파일을 변환하지 못했습니다.") from exc


def _convert_video_to_gif(video_bytes: bytes, video_format: str) -> bytes:
    if not video_bytes:
        raise HTTPException(status_code=400, detail="비디오 파일이 비어있습니다.")
    if len(video_bytes) > MAX_VIDEO_BYTES:
        mb = MAX_VIDEO_BYTES // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"비디오는 최대 {mb}MB까지 지원됩니다.")

    work_dir = Path(tempfile.mkdtemp(prefix="postcard-"))
    best_bytes: Optional[bytes] = None
    suffix = ".webm" if video_format.lower() == "webm" else ".mp4"

    try:
        input_path = work_dir / f"clip{suffix}"
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

                fps = clip.fps or TARGET_GIF_FPS
                clip = clip.with_fps(min(int(fps), preset.fps))

                clip.write_gif(str(output_path), fps=clip.fps)

            _optimize_gif_file(output_path, preset)

            if not output_path.exists():
                raise HTTPException(status_code=500, detail="GIF 파일을 생성하지 못했습니다.")

            gif_bytes = output_path.read_bytes()
            if best_bytes is None or len(gif_bytes) < len(best_bytes):
                best_bytes = gif_bytes
            if len(gif_bytes) <= MAX_VIDEO_BYTES:
                return gif_bytes

        assert best_bytes is not None
        return best_bytes
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("영상 GIF 변환 실패: %s", exc)
        raise HTTPException(status_code=500, detail=f"GIF 변환 중 오류가 발생했습니다: {exc}") from exc
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


class PostcardEmailPayload(BaseModel):
    recipient: EmailStr = Field(...)
    front_card_png: bytes
    back_card_png: bytes
    front_gif: bytes
    back_gif: bytes

    @classmethod
    def build(
        cls,
        *,
        recipient: str,
        front_card_image: bytes,
        back_card_image: bytes,
        front_video_bytes: bytes,
        back_video_bytes: bytes,
        front_video_format: str,
        back_video_format: str,
    ) -> "PostcardEmailPayload":
        front_png = _normalize_image(front_card_image)
        back_png = _normalize_image(back_card_image)
        front_gif = _convert_video_to_gif(front_video_bytes, front_video_format)
        back_gif = _convert_video_to_gif(back_video_bytes, back_video_format)
        return cls(
            recipient=recipient,
            front_card_png=front_png,
            back_card_png=back_png,
            front_gif=front_gif,
            back_gif=back_gif,
        )


def _build_text_body(payload: PostcardEmailPayload) -> str:
    return "\n".join(
        [
            "This is for you",
            "",
            "정적 카드와 동적 카드 이미지를 확인해주세요.",
        ]
    )


def _build_html_body() -> str:
    return """
<!doctype html>
<html>
  <body style="margin:0;padding:24px;background:#f3f4f6;font-family:'Pretendard','Apple SD Gothic Neo',Arial,sans-serif;color:#111827;">
    <table role="presentation" style="width:100%;max-width:680px;margin:0 auto;background:#ffffff;border-radius:20px;padding:32px;border:1px solid #e5e7eb;">
      <tr>
        <td style="text-align:center;">
          <h2 style="margin:0 0 24px 0;font-size:26px;">This is for you</h2>

          <div style="display:flex;flex-direction:column;gap:28px;">
            <img src="cid:front-card-static" alt="Front card" style="width:100%;border-radius:16px;display:block;"/>
            <img src="cid:back-card-static" alt="Back card" style="width:100%;border-radius:16px;display:block;"/>
            <img src="cid:front-card-gif" alt="Front animation" style="width:100%;border-radius:16px;display:block;"/>
            <img src="cid:back-card-gif" alt="Back animation" style="width:100%;border-radius:16px;display:block;"/>
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


def _build_message(payload: PostcardEmailPayload) -> MIMEMultipart:
    subject = "This is for you"
    text_body = _build_text_body(payload)
    html_body = _build_html_body()

    root = MIMEMultipart("related")
    root["Subject"] = subject
    root["From"] = os.getenv("MAIL_FROM") or os.getenv("MAIL_USERNAME") or ""
    root["To"] = str(payload.recipient)

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(text_body, "plain", "utf-8"))
    alternative.attach(MIMEText(html_body, "html", "utf-8"))
    root.attach(alternative)

    attachments = [
        ("front-card-static", "front-card.png", "image/png", payload.front_card_png),
        ("back-card-static", "back-card.png", "image/png", payload.back_card_png),
        ("front-card-gif", "front-card.gif", "image/gif", payload.front_gif),
        ("back-card-gif", "back-card.gif", "image/gif", payload.back_gif),
    ]

    for cid, filename, content_type, data in attachments:
        subtype = content_type.split("/", 1)[1]
        mime_image = MIMEImage(data, _subtype=subtype)
        mime_image.add_header("Content-ID", f"<{cid}>")
        mime_image.add_header("Content-Disposition", "inline", filename=filename)
        root.attach(mime_image)

    return root


def send_postcard_email(payload: PostcardEmailPayload) -> None:
    smtp_server = os.getenv("MAIL_SERVER")
    smtp_port = int(os.getenv("MAIL_PORT", "587"))
    smtp_user = os.getenv("MAIL_USERNAME")
    smtp_pass = os.getenv("MAIL_PASSWORD")
    from_email = os.getenv("MAIL_FROM") or smtp_user
    from_name = os.getenv("MAIL_FROM_NAME") or ""
    use_starttls = _env_bool("MAIL_STARTTLS", True)
    use_ssl_tls = _env_bool("MAIL_SSL_TLS", False)

    if not all([smtp_server, smtp_port, smtp_user, smtp_pass, from_email]):
        raise HTTPException(status_code=500, detail="메일 환경변수가 올바르게 설정되지 않았습니다.")

    message = _build_message(payload)
    message.replace_header("From", f"{from_name} <{from_email}>" if from_name else from_email)
    message.replace_header("To", str(payload.recipient))

    try:
        if use_ssl_tls:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)

        with server:
            if use_starttls and not use_ssl_tls:
                server.starttls(context=ssl.create_default_context())
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_email, [str(payload.recipient)], message.as_string())
    except Exception as exc:
        logger.exception("SMTP 전송 실패: %s", exc)
        raise HTTPException(status_code=502, detail="메일 전송에 실패했습니다.") from exc
