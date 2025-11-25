import json
import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Literal, Optional

from fastapi import HTTPException
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

    front_preview = payload.front.drawingFourier[0][:2] if payload.front.drawingFourier else []
    back_preview = payload.back.textFourier[0][:2] if payload.back.textFourier else []

    front_preview_json = json.dumps([c.model_dump() for c in front_preview], ensure_ascii=False)
    back_preview_json = json.dumps([c.model_dump() for c in back_preview], ensure_ascii=False)

    return f"""
<!doctype html>
<html>
  <body style="font-family: Arial, sans-serif; background: #f7f8fa; padding: 24px; color: #1f2933;">
    <table role="presentation" style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.04); padding: 24px; border: 1px solid #e5e7eb;">
      <tr>
        <td>
          <h2 style="margin: 0 0 12px 0; color: #111827;">Postcard for {recipient}</h2>
          <p style="margin: 0 0 16px 0; color: #4b5563;">Template: {payload.templateName} ({payload.templateId})</p>

          <div style="padding: 16px; border: 1px solid #e5e7eb; border-radius: 10px; background: #f9fafb; margin-bottom: 16px;">
            <p style="margin: 0 0 8px 0; font-weight: 600;">Front</p>
            <p style="margin: 0 0 4px 0;">Background: <span style="font-family: monospace;">{payload.front.background}</span></p>
            <p style="margin: 0 0 4px 0;">Strokes: {front_rows} rows / {front_total} coefficients</p>
            <p style="margin: 0; font-size: 12px; color: #6b7280;">Preview: {front_preview_json}</p>
          </div>

          <div style="padding: 16px; border: 1px solid #e5e7eb; border-radius: 10px; background: #f9fafb; margin-bottom: 16px;">
            <p style="margin: 0 0 8px 0; font-weight: 600;">Back</p>
            <p style="margin: 0 0 4px 0;">Recipient: {payload.back.recipient}</p>
            <p style="margin: 0 0 4px 0;">Signature: {payload.back.signature or '-'}</p>
            <p style="margin: 0 0 4px 0;">Message preview: {payload.back.messagePreview or '-'}</p>
            <p style="margin: 0 0 4px 0;">Strokes: {back_rows} rows / {back_total} coefficients</p>
            <p style="margin: 0; font-size: 12px; color: #6b7280;">Preview: {back_preview_json}</p>
          </div>

          <p style="margin: 0; color: #6b7280; font-size: 12px;">Sent at {payload.createdAt.isoformat()}</p>
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
