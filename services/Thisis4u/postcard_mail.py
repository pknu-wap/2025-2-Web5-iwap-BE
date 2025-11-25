import json
import logging
import math
import os
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import List, Literal, Optional, Tuple

from fastapi import HTTPException
from pydantic import BaseModel, EmailStr, field_validator, model_validator


TAU = math.tau if hasattr(math, "tau") else 2 * math.pi
SVG_WIDTH = 520
SVG_HEIGHT = 320
SVG_PADDING = 24
SVG_STROKE_WIDTH = 2.2
FOURIER_SAMPLES = int(os.getenv("THISIS4U_FOURIER_SAMPLES", "420"))
COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")
Point = Tuple[float, float]


def _sanitize_hex_color(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("컬러값은 문자열이어야 합니다.")
    stripped = value.strip()
    if COLOR_PATTERN.match(stripped):
        return stripped.lower()
    raise ValueError("HEX 컬러코드 형식(#RRGGBB)만 허용됩니다.")


def _format_html_text(value: Optional[str], placeholder: str = "-") -> str:
    if not value:
        return placeholder
    return escape(value).replace("\n", "<br />")


def _count_coefficients(matrix: List[List["FourierCoefficient"]]) -> int:
    return sum(len(row) for row in matrix)


class FourierCoefficient(BaseModel):
    amp: float
    freq: int
    phase: float


class FrontPayload(BaseModel):
    background: str
    drawingFourier: List[List[FourierCoefficient]]

    @field_validator("background")
    @classmethod
    def validate_background(cls, value: str):
        return _sanitize_hex_color(value)

    @field_validator("drawingFourier")
    @classmethod
    def validate_drawing(cls, value: List[List[FourierCoefficient]]):
        if not value:
            raise ValueError("drawingFourier는 최소 1개 이상이어야 합니다.")
        return value


class BackPayload(BaseModel):
    recipient: EmailStr
    signature: Optional[str] = None
    messagePreview: Optional[str] = None
    textFourier: List[List[FourierCoefficient]]

    @field_validator("textFourier")
    @classmethod
    def validate_text(cls, value: List[List[FourierCoefficient]]):
        if not value:
            raise ValueError("textFourier는 최소 1개 이상이어야 합니다.")
        return value

    @field_validator("signature", "messagePreview")
    @classmethod
    def limit_length(cls, value: Optional[str]):
        if value and len(value) > 200:
            raise ValueError("signature와 messagePreview는 200자 이하로 보내주세요.")
        return value


class SendPostcardRequest(BaseModel):
    templateId: Literal["this-is-for-u"]
    templateName: Literal["Th!s !s for u"]
    createdAt: datetime
    front: FrontPayload
    back: BackPayload

    @model_validator(mode="after")
    def validate_sizes(self):
        front_total = _count_coefficients(self.front.drawingFourier)
        back_total = _count_coefficients(self.back.textFourier)
        if front_total + back_total > 20000:
            raise ValueError("Fourier 계수는 총 20000개 이하로 보내주세요.")
        return self


def _fourier_stroke_points(row: List["FourierCoefficient"], samples: int = FOURIER_SAMPLES) -> List[Point]:
    if not row:
        return []

    points: List[Point] = []
    for step in range(samples):
        t = (step / samples) * TAU
        x_sum = 0.0
        y_sum = 0.0
        for coeff in row:
            angle = coeff.phase + coeff.freq * t
            x_sum += coeff.amp * math.cos(angle)
            y_sum += coeff.amp * math.sin(angle)
        points.append((x_sum, y_sum))
    return points


def _normalize_points(
    strokes: List[List[Point]],
    width: int = SVG_WIDTH,
    height: int = SVG_HEIGHT,
    padding: int = SVG_PADDING,
) -> List[List[Point]]:
    if not strokes:
        return []

    flat_points = [pt for stroke in strokes for pt in stroke]
    xs = [p[0] for p in flat_points]
    ys = [p[1] for p in flat_points]

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    avail_w = max(width - 2 * padding, 1.0)
    avail_h = max(height - 2 * padding, 1.0)
    scale = min(avail_w / span_x, avail_h / span_y)
    scale = scale if math.isfinite(scale) and scale > 0 else 1.0

    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2

    normalized: List[List[Point]] = []
    for stroke in strokes:
        normalized.append(
            [
                (
                    (pt[0] - center_x) * scale + width / 2,
                    (center_y - pt[1]) * scale + height / 2,
                )
                for pt in stroke
            ]
        )
    return normalized


def _render_placeholder_svg(background: str, stroke_color: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SVG_WIDTH}" height="{SVG_HEIGHT}" '
        f'viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}" role="img" aria-label="Empty Fourier preview">'
        f'<rect width="100%" height="100%" rx="32" fill="{background}"/>'
        f'<text x="50%" y="50%" text-anchor="middle" fill="{stroke_color}" font-size="18" '
        f'font-family="Arial, sans-serif">No strokes</text>'
        "</svg>"
    )


def _render_fourier_svg(
    matrix: List[List["FourierCoefficient"]],
    background: str,
    stroke_color: str,
) -> str:
    strokes: List[List[Point]] = []
    for row in matrix:
        pts = _fourier_stroke_points(row)
        if pts:
            strokes.append(pts)

    if not strokes:
        return _render_placeholder_svg(background, stroke_color)

    normalized = _normalize_points(strokes)
    polylines = []
    for stroke in normalized:
        if len(stroke) < 2:
            continue
        points_attr = " ".join(f"{x:.2f},{y:.2f}" for x, y in stroke)
        polylines.append(
            f'<polyline fill="none" stroke="{stroke_color}" stroke-width="{SVG_STROKE_WIDTH}" '
            'stroke-linecap="round" stroke-linejoin="round" points="'
            f"{points_attr}\" />"
        )

    if not polylines:
        return _render_placeholder_svg(background, stroke_color)

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SVG_WIDTH}" height="{SVG_HEIGHT}" '
        f'viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}" role="img" aria-label="Fourier stroke preview">'
        f'<rect width="100%" height="100%" rx="32" fill="{background}"/>'
        + "".join(polylines)
        + "</svg>"
    )


def _build_text_body(payload: SendPostcardRequest, recipient: str) -> str:
    front_rows = len(payload.front.drawingFourier)
    back_rows = len(payload.back.textFourier)
    front_total = _count_coefficients(payload.front.drawingFourier)
    back_total = _count_coefficients(payload.back.textFourier)

    front_preview = payload.front.drawingFourier[0][:2] if payload.front.drawingFourier else []
    back_preview = payload.back.textFourier[0][:2] if payload.back.textFourier else []

    body_lines = [
        f"Postcard for {recipient}",
        f"Template: {payload.templateId} ({payload.templateName})",
        f"Created at: {payload.createdAt.isoformat()}",
        f"Recipient: {payload.back.recipient}",
        f"Signature: {payload.back.signature or '-'}",
        f"Message preview: {payload.back.messagePreview or '-'}",
        f"Front background: {payload.front.background}",
        f"Front strokes: {front_rows} rows / {front_total} coefficients",
        f"Back strokes: {back_rows} rows / {back_total} coefficients",
        "",
        "Preview (first row, up to 2 coefficients each):",
        f"Front[0]: {json.dumps([c.model_dump() for c in front_preview], ensure_ascii=False)}",
        f"Back[0]: {json.dumps([c.model_dump() for c in back_preview], ensure_ascii=False)}",
    ]
    return "\n".join(body_lines)


def _build_html_body(payload: SendPostcardRequest, recipient: str) -> str:
    front_rows = len(payload.front.drawingFourier)
    back_rows = len(payload.back.textFourier)
    front_total = _count_coefficients(payload.front.drawingFourier)
    back_total = _count_coefficients(payload.back.textFourier)

    recipient_html = escape(recipient)
    signature_html = _format_html_text(payload.back.signature)
    message_html = _format_html_text(payload.back.messagePreview, placeholder="-")

    front_svg = _render_fourier_svg(
        payload.front.drawingFourier,
        payload.front.background,
        stroke_color="#fef9c3",
    )
    back_svg = _render_fourier_svg(
        payload.back.textFourier,
        background="#ffffff",
        stroke_color="#111827",
    )

    return f"""
<!doctype html>
<html>
  <body style="font-family: Arial, sans-serif; background: #f3f4f6; padding: 32px 16px; color: #111827;">
    <div style="max-width: 720px; margin: 0 auto; background: #ffffff; border-radius: 16px; border: 1px solid #e5e7eb; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08); padding: 28px;">
      <h2 style="margin: 0 0 8px 0;">Postcard for {recipient_html}</h2>
      <p style="margin: 0 0 20px 0; color: #6b7280;">Template · {payload.templateName} ({payload.templateId}) · {payload.createdAt.isoformat()}</p>

      <div style="display: flex; flex-wrap: wrap; gap: 16px;">
        <div style="flex: 1 1 260px; border: 1px solid #e5e7eb; border-radius: 14px; padding: 16px; background: #f9fafb;">
          <p style="margin: 0 0 8px 0; font-weight: 600;">Front</p>
          <div style="margin-bottom: 12px; border-radius: 24px; overflow: hidden; border: 1px solid rgba(0,0,0,0.05);">{front_svg}</div>
          <p style="margin: 0 0 4px 0; font-size: 13px; color: #374151;">Background: <span style="font-family: monospace;">{payload.front.background}</span></p>
          <p style="margin: 0; font-size: 12px; color: #6b7280;">{front_rows} rows · {front_total} coefficients</p>
        </div>

        <div style="flex: 1 1 260px; border: 1px solid #e5e7eb; border-radius: 14px; padding: 16px; background: #f9fafb;">
          <p style="margin: 0 0 8px 0; font-weight: 600;">Back</p>
          <div style="margin-bottom: 12px; border-radius: 24px; overflow: hidden; border: 1px solid rgba(0,0,0,0.05);">{back_svg}</div>
          <div style="font-size: 13px; color: #374151; line-height: 1.5;">
            <p style="margin: 0;">Recipient: {escape(payload.back.recipient)}</p>
            <p style="margin: 0;">Signature: {signature_html}</p>
            <p style="margin: 8px 0 0 0;">Message:</p>
            <p style="margin: 0; padding: 8px 10px; background: #fff; border: 1px dashed #d1d5db; border-radius: 8px;">{message_html}</p>
          </div>
          <p style="margin: 12px 0 0 0; font-size: 12px; color: #6b7280;">{back_rows} rows · {back_total} coefficients</p>
        </div>
      </div>

      <p style="margin: 24px 0 0 0; font-size: 12px; color: #94a3b8;">자동 생성된 SSR 미리보기입니다.</p>
    </div>
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
                server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_email, [to_email], msg.as_string())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SMTP 전송 실패: {exc}") from exc

    return True


def send_postcard_email(payload: SendPostcardRequest):
    recipient_email = payload.back.recipient
    subject = f"[Postcard] {payload.templateName}"
    text_body = _build_text_body(payload, recipient_email)
    html_body = _build_html_body(payload, recipient_email)

    try:
        send_email(recipient_email, subject, html_body, text_body)
        logging.info("Postcard mail sent to %s", recipient_email)
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("메일 전송 실패: %s", exc)
        raise HTTPException(status_code=502, detail="메일 전송에 실패했습니다.") from exc
