import json
import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Literal, Optional

from fastapi import HTTPException
from jinja2 import BaseLoader, Environment, select_autoescape
from pydantic import BaseModel, EmailStr, field_validator, model_validator


def _count_coefficients(matrix: List[List["FourierCoefficient"]]) -> int:
    return sum(len(row) for row in matrix)


class FourierCoefficient(BaseModel):
    amp: float
    freq: int
    phase: float


class FrontPayload(BaseModel):
    background: str
    drawingFourier: List[List[FourierCoefficient]]

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


_PREVIEW_ROW_LIMIT = 4
_PREVIEW_COEFF_LIMIT = 5
_SSR_ENV = Environment(
    loader=BaseLoader(),
    autoescape=select_autoescape(enabled_extensions=("html", "xml")),
)
_POSTCARD_TEMPLATE = _SSR_ENV.from_string(
    """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Postcard for {{ header.recipient }}</title>
    <style>
      :root { color-scheme: light; }
      body {
        margin: 0;
        padding: 24px;
        font-family: 'Pretendard', 'Segoe UI', Arial, sans-serif;
        background: #f5f6fa;
        color: #1f2933;
      }
      .wrapper {
        max-width: 760px;
        margin: 0 auto;
        background: #ffffff;
        border-radius: 16px;
        box-shadow: 0 20px 45px rgba(15, 23, 42, 0.08);
        border: 1px solid #e5e7eb;
        padding: 28px 32px;
      }
      h1 {
        margin: 0 0 6px 0;
        font-size: 22px;
      }
      .subtitle {
        margin: 0 0 18px 0;
        color: #6b7280;
        font-size: 14px;
      }
      .faces {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        gap: 18px;
      }
      .face {
        border: 1px solid #e5e7eb;
        border-radius: 14px;
        padding: 18px;
        background: #f9fafb;
      }
      .face h3 {
        margin: 0 0 6px 0;
      }
      .meta {
        margin: 0 0 12px 0;
        padding: 0;
        list-style: none;
        color: #4b5563;
        font-size: 13px;
      }
      .meta li {
        margin-bottom: 4px;
      }
      .color-chip {
        display: inline-flex;
        align-items: center;
        gap: 8px;
      }
      .color-chip__preview {
        width: 16px;
        height: 16px;
        border-radius: 6px;
        border: 1px solid rgba(0,0,0,0.08);
      }
      .rows {
        border-top: 1px dashed #e5e7eb;
        padding-top: 12px;
        margin-top: 12px;
      }
      .row {
        margin-bottom: 10px;
      }
      .row strong {
        font-size: 13px;
      }
      .coeff-list {
        margin: 6px 0;
        padding-left: 18px;
        color: #111827;
      }
      .etc {
        color: #9ca3af;
        font-size: 12px;
      }
      .divider {
        height: 1px;
        background: #e5e7eb;
        margin: 20px 0;
      }
    </style>
  </head>
  <body>
    <div class="wrapper">
      <h1>Postcard for {{ header.recipient }}</h1>
      <p class="subtitle">
        Template {{ header.template_label }} ({{ header.template_id }}) ·
        Sent at {{ header.created_at }}
      </p>
      <div class="faces">
        {% for face in faces %}
          <section class="face">
            <h3>{{ face.title }}</h3>
            <p class="subtitle">{{ face.subtitle }}</p>
            <ul class="meta">
              <li>Strokes: {{ face.total_rows }} rows / {{ face.total_coefficients }} coefficients</li>
              {% if face.background %}
                <li class="color-chip">
                  Background:
                  <span class="color-chip__preview" style="background: {{ face.background }};"></span>
                  <code>{{ face.background }}</code>
                </li>
              {% endif %}
              {% if face.recipient %}
                <li>Recipient: {{ face.recipient }}</li>
              {% endif %}
              {% if face.signature %}
                <li>Signature: {{ face.signature }}</li>
              {% endif %}
              {% if face.message_preview %}
                <li>Message: {{ face.message_preview }}</li>
              {% endif %}
            </ul>
            <div class="rows">
              {% for row in face.rows %}
                <div class="row">
                  <strong>Row {{ row.index }}</strong>
                  <ul class="coeff-list">
                    {% for coeff in row.coefficients %}
                      <li>amp {{ coeff.amp }}, freq {{ coeff.freq }}, phase {{ coeff.phase }}</li>
                    {% endfor %}
                  </ul>
                  {% if row.remaining_coefficients > 0 %}
                    <p class="etc">… 외 {{ row.remaining_coefficients }} coefficients</p>
                  {% endif %}
                </div>
              {% endfor %}
              {% if face.remaining_rows > 0 %}
                <p class="etc">Row {{ face.remaining_rows }}개 더 있음</p>
              {% endif %}
            </div>
          </section>
        {% endfor %}
      </div>
    </div>
  </body>
</html>
"""
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


def _preview_rows(matrix: List[List[FourierCoefficient]]):
    preview_rows = []
    for idx, row in enumerate(matrix[:_PREVIEW_ROW_LIMIT]):
        preview_rows.append(
            {
                "index": idx + 1,
                "coefficients": [
                    coeff.model_dump() for coeff in row[:_PREVIEW_COEFF_LIMIT]
                ],
                "remaining_coefficients": max(len(row) - _PREVIEW_COEFF_LIMIT, 0),
            }
        )
    remaining_rows = max(len(matrix) - _PREVIEW_ROW_LIMIT, 0)
    return preview_rows, remaining_rows


def _build_ssr_context(payload: SendPostcardRequest, recipient: str):
    front_rows, front_remaining = _preview_rows(payload.front.drawingFourier)
    back_rows, back_remaining = _preview_rows(payload.back.textFourier)

    faces = [
        {
            "id": "front",
            "title": "Front",
            "subtitle": "카드 앞면",
            "background": payload.front.background,
            "rows": front_rows,
            "remaining_rows": front_remaining,
            "total_rows": len(payload.front.drawingFourier),
            "total_coefficients": _count_coefficients(payload.front.drawingFourier),
            "recipient": None,
            "signature": None,
            "message_preview": None,
        },
        {
            "id": "back",
            "title": "Back",
            "subtitle": "카드 뒷면",
            "background": None,
            "rows": back_rows,
            "remaining_rows": back_remaining,
            "total_rows": len(payload.back.textFourier),
            "total_coefficients": _count_coefficients(payload.back.textFourier),
            "recipient": payload.back.recipient,
            "signature": payload.back.signature,
            "message_preview": payload.back.messagePreview,
        },
    ]

    return {
        "header": {
            "recipient": recipient,
            "template_label": payload.templateName,
            "template_id": payload.templateId,
            "created_at": payload.createdAt.isoformat(),
        },
        "faces": faces,
    }


def _build_html_body(payload: SendPostcardRequest, recipient: str) -> str:
    context = _build_ssr_context(payload, recipient)
    return _POSTCARD_TEMPLATE.render(context)


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

    try:
        html_body = _build_html_body(payload, recipient_email)
    except Exception as exc:
        logging.exception("SSR 렌더링 실패: %s", exc)
        raise HTTPException(status_code=500, detail="SSR 렌더링에 실패했습니다.") from exc

    try:
        send_email(recipient_email, subject, html_body, text_body)
        logging.info("Postcard mail sent to %s", recipient_email)
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("메일 전송 실패: %s", exc)
        raise HTTPException(status_code=502, detail="메일 전송에 실패했습니다.") from exc
