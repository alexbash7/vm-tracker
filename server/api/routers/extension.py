from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from datetime import datetime
import uuid
import os
import re
import boto3
from botocore.exceptions import ClientError

from database import get_db
from models import ExtensionProfile, CookieVault, BlockingRule, Machine, ActivityEvent, Screenshot
from schemas import HandshakeRequest, AgentConfigResponse, TelemetryBatch

# ============ CONFIG ============

# Google OAuth
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", None)

# S3 (Wasabi)
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "https://s3.wasabisys.com")
S3_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
S3_BUCKET = os.getenv("S3_BUCKET", "instaloader")
S3_SCREENSHOTS_PREFIX = "screenshots/"  # Папка внутри бакета

# Ограничения
MAX_FILE_SIZE_MB = 5
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}

# ============ S3 CLIENT ============

def get_s3_client():
    """Создаёт S3 клиент для Wasabi."""
    return boto3.client(
        's3',
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY
    )

# ============ HELPERS ============

def sanitize_filename(email: str) -> str:
    """
    Убирает опасные символы из email для безопасного имени файла.
    """
    return re.sub(r'[^a-zA-Z0-9@._-]', '_', email)


import requests as http_requests  # Переименовываем чтобы не конфликтовать с google.auth.transport.requests

def verify_google_user(token: str, expected_email: str) -> dict:
    """
    Проверяет Google OAuth Access Token через Google API.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing auth token")

    try:
        # Валидируем Access Token через Google tokeninfo endpoint
        response = http_requests.get(
            f"https://oauth2.googleapis.com/tokeninfo?access_token={token}"
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        token_info = response.json()
        token_email = token_info.get("email")
        
        if not token_email:
            raise HTTPException(status_code=401, detail="Token has no email scope")
        
        if token_email != expected_email:
            raise HTTPException(status_code=403, detail="Token email does not match request email")

        return token_info

    except http_requests.RequestException as e:
        raise HTTPException(status_code=401, detail=f"Token validation failed: {str(e)}")
# ============ ROUTER ============

router = APIRouter(prefix="/api/extension", tags=["extension"])


@router.post("/handshake", response_model=AgentConfigResponse)
async def handshake(req: HandshakeRequest, db: Session = Depends(get_db)):
    """
    Расширение стучится при запуске.
    Проверяем юзера, отдаем конфиг, куки и правила.
    """
    id_info = verify_google_user(req.auth_token, req.email)
    google_sub = id_info.get("sub")
    
    profile = db.query(ExtensionProfile).filter(ExtensionProfile.email == req.email).first()

    if not profile:
        profile = ExtensionProfile(
            email=req.email,
            google_sub_id=google_sub
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    elif profile.google_sub_id is None and google_sub:
        profile.google_sub_id = google_sub
        db.commit()

    # Kill Switch
    if not profile.is_active:
        return {
            "status": "banned",
            "idle_threshold_sec": 60,
            "screenshot_interval_sec": 300,
            "cookies": [],
            "blocking_rules": []
        }

    # Получаем только неинжектированные куки
    cookies = db.query(CookieVault).filter(
        CookieVault.profile_id == profile.id,
        CookieVault.injected_at.is_(None)
    ).all()

    cookies_list = [
        {
            "id": c.id,
            "domain": c.domain,
            "name": c.name,
            "value": c.value,
            "path": c.path,
            "secure": c.secure,
            "expiration_date": c.expiration_date
        }
        for c in cookies
    ]

    rules_list = [
        {"pattern": r.pattern, "action": r.action}
        for r in profile.blocking_rules
    ]

    return {
        "status": "active",
        "idle_threshold_sec": profile.idle_threshold_sec,
        "screenshot_interval_sec": profile.screenshot_interval_sec,
        "config_refresh_sec": 300,
        "cookies": cookies_list,
        "blocking_rules": rules_list
    }

@router.post("/telemetry")
async def ingest_telemetry(batch: TelemetryBatch, db: Session = Depends(get_db)):
    """
    Прием пачки логов (раз в минуту).
    """
    verify_google_user(batch.auth_token, batch.email)

    machine = db.query(Machine).filter(Machine.machine_id == batch.email).first()

    if not machine:
        machine = Machine(
            id=uuid.uuid4(),
            machine_id=batch.email,
            machine_type="browser_extension",
            user_label=f"Extension: {batch.email}",
            is_active=True
        )
        db.add(machine)
        db.commit()
        db.refresh(machine)

    machine.last_seen_at = datetime.now()

    count = 0
    for item in batch.events:
        event = ActivityEvent(
            machine_id=machine.id,
            timestamp=item.start_ts,
            duration_seconds=item.duration_sec,

            active_domain=item.domain,
            active_url=item.url,
            active_app="Google Chrome",
            active_window=item.window_title or item.domain,

            mouse_clicks=item.clicks,
            key_count=item.keypresses,
            scroll_count=item.scroll_px,
            mouse_distance_px=item.mouse_px,
            focus_time_sec=item.focus_time_sec,
            
            is_idle=item.is_idle,
            agent_type="extension"
        )
        db.add(event)
        count += 1

    db.commit()
    return {"status": "ok", "saved_events": count}


@router.post("/screenshot")
async def upload_screenshot(
    file: UploadFile = File(...),
    email: str = Form(...),
    auth_token: str = Form(...),
    created_at_ts: float = Form(...),
    db: Session = Depends(get_db)
):
    """
    Принимает скриншот и загружает в S3 (Wasabi).
    """
    # 1. Авторизация
    verify_google_user(auth_token, email)

    # 2. Валидация файла
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {file.content_type}. Allowed: {ALLOWED_CONTENT_TYPES}"
        )

    contents = await file.read()
    file_size_mb = len(contents) / (1024 * 1024)

    if file_size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"File too large: {file_size_mb:.1f}MB. Max: {MAX_FILE_SIZE_MB}MB"
        )

    # 3. Находим машину
    machine = db.query(Machine).filter(Machine.machine_id == email).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not initialized via telemetry yet")

    # 4. Генерируем имя файла и S3 ключ
    safe_email = sanitize_filename(email)
    extension = file.content_type.split("/")[-1]
    if extension == "jpeg":
        extension = "jpg"
    
    # Структура: screenshots/2025/01/15/email_timestamp.jpg
    dt = datetime.fromtimestamp(created_at_ts)
    date_path = dt.strftime("%Y/%m/%d")
    filename = f"{safe_email}_{int(created_at_ts)}.{extension}"
    s3_key = f"{S3_SCREENSHOTS_PREFIX}{date_path}/{filename}"

    # 5. Загружаем в S3
    try:
        s3 = get_s3_client()
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=contents,
            ContentType=file.content_type
        )
    except ClientError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload to S3: {str(e)}"
        )

    # 6. Формируем URL для доступа
    s3_url = f"{S3_ENDPOINT}/{S3_BUCKET}/{s3_key}"

    # 7. Сохраняем в БД
    screenshot = Screenshot(
        machine_id=machine.id,
        timestamp=dt,
        image_path=s3_url,
        thumbnail_path=s3_url  # TODO: генерировать thumbnail
    )

    db.add(screenshot)
    db.commit()

    return {
        "status": "ok",
        "file": filename,
        "s3_key": s3_key,
        "url": s3_url
    }


@router.post("/cookies-injected")
async def mark_cookies_injected(
    request: Request,
    db: Session = Depends(get_db)
):
    data = await request.json()
    cookie_ids = data.get("cookie_ids", [])
    
    if cookie_ids:
        db.query(CookieVault).filter(
            CookieVault.id.in_(cookie_ids)
        ).update({CookieVault.injected_at: func.now()}, synchronize_session=False)
        db.commit()
    
    return {"status": "ok"}