from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from typing import List


from database import get_db
from models import Machine, ActivityEvent
from schemas import ActivityEventCreate, EventsBatch

router = APIRouter(prefix="/api", tags=["ingest"])


def get_or_create_machine(db: Session, machine_id: str, agent_type: str = "desktop") -> Machine:
    """Найти машину или создать новую автоматически"""
    machine = db.query(Machine).filter(Machine.machine_id == machine_id).first()
    
    if not machine:
        machine = Machine(
            machine_id=machine_id,
            user_label=machine_id,  # по умолчанию = machine_id, потом можно переименовать
            machine_type="vps" if "vm-" in machine_id else "local",
            is_active=True
        )
        db.add(machine)
        db.commit()
        db.refresh(machine)
    
    return machine


@router.post("/events")
async def receive_events(batch: EventsBatch, db: Session = Depends(get_db)):
    """Приём пачки событий от агента"""
    
    processed = 0
    machines_updated = set()
    
    for event_data in batch.events:
        # Получить или создать машину
        machine = get_or_create_machine(db, event_data.machine_id, event_data.agent_type)
        machines_updated.add(machine.id)
        
        # Создать событие
# Создать событие
# Создать событие
        event = ActivityEvent(
            machine_id=machine.id,
            timestamp=event_data.timestamp,
            key_count=event_data.key_count,
            mouse_clicks=event_data.mouse_clicks,
            mouse_distance_px=event_data.mouse_distance_px,
            scroll_count=event_data.scroll_count,
            active_window=event_data.active_window,
            active_app=event_data.active_app,
            is_idle=event_data.is_idle,
            active_url=event_data.active_url,
            active_domain=event_data.active_domain,
            tab_switches_count=event_data.tab_switches_count,
            cpu_percent=event_data.cpu_percent,
            ram_used_percent=event_data.ram_used_percent,
            disk_used_percent=event_data.disk_used_percent,
            agent_type=event_data.agent_type,
            # NEW fields
            duration_seconds=event_data.duration_seconds,
            focus_time_sec=event_data.focus_time_sec,
            copy_count=event_data.copy_count,
            paste_count=event_data.paste_count,
            keys_array=event_data.keys_array,
            mouse_avg_speed=event_data.mouse_avg_speed,
        )
        db.add(event)
        db.flush()  # ← ДОБАВЬ это, чтобы получить event.id
        
        # ← ДОБАВЬ весь этот блок:
        # Сохраняем clipboard history в отдельную таблицу
        if event_data.clipboard_history:
            from models import ClipboardEvent
            for clip_item in event_data.clipboard_history:
                clipboard_event = ClipboardEvent(
                    activity_event_id=event.id,
                    action=clip_item.action,
                    content=clip_item.text
                )
                db.add(clipboard_event)
        
        processed += 1
    
    # Обновить last_seen_at для всех затронутых машин
    db.query(Machine).filter(Machine.id.in_(machines_updated)).update(
        {Machine.last_seen_at: func.now()},
        synchronize_session=False
    )
    
    db.commit()
    
    return {"status": "ok", "processed": processed}


@router.post("/event")
async def receive_single_event(event_data: ActivityEventCreate, db: Session = Depends(get_db)):
    """Приём одного события (для простоты тестирования)"""
    batch = EventsBatch(events=[event_data])
    return await receive_events(batch, db)


@router.post("/desktop/screenshot")
async def upload_desktop_screenshot(
    file: UploadFile = File(...),
    machine_id: str = Form(...),
    created_at_ts: float = Form(...),
    source_window: str = Form(None),
    source_app: str = Form(None),
    db: Session = Depends(get_db)
):
    """
    Принимает скриншот от desktop трекера и загружает в S3.
    """
    from datetime import datetime
    import uuid
    import os
    import boto3
    from botocore.exceptions import ClientError
    
    # S3 config
    S3_ENDPOINT = os.getenv("S3_ENDPOINT", "https://s3.wasabisys.com")
    S3_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
    S3_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    S3_BUCKET = os.getenv("S3_BUCKET", "instaloader")
    S3_SCREENSHOTS_PREFIX = "screenshots/"
    
    ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
    MAX_FILE_SIZE_MB = 5

    # 1. Валидация файла
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {file.content_type}"
        )

    contents = await file.read()
    file_size_mb = len(contents) / (1024 * 1024)

    if file_size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"File too large: {file_size_mb:.1f}MB"
        )

    # 2. Находим или создаём машину
    machine = db.query(Machine).filter(Machine.machine_id == machine_id).first()
    if not machine:
        machine = Machine(
            machine_id=machine_id,
            user_label=machine_id,
            machine_type="vps" if "vm-" in machine_id else "local",
            is_active=True
        )
        db.add(machine)
        db.commit()
        db.refresh(machine)

    # 3. Генерируем имя файла
    import re
    safe_id = re.sub(r'[^a-zA-Z0-9._-]', '_', machine_id)
    extension = file.content_type.split("/")[-1]
    if extension == "jpeg":
        extension = "jpg"
    
    dt = datetime.fromtimestamp(created_at_ts)
    date_path = dt.strftime("%Y/%m/%d")
    filename = f"{safe_id}_{int(created_at_ts)}.{extension}"
    s3_key = f"{S3_SCREENSHOTS_PREFIX}{date_path}/{filename}"

    # 4. Загружаем в S3
    try:
        s3 = boto3.client(
            's3',
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY
        )
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

    # 5. URL для доступа
    s3_url = f"{S3_ENDPOINT}/{S3_BUCKET}/{s3_key}"

    # 6. Сохраняем в БД
    from models import Screenshot
    screenshot = Screenshot(
        machine_id=machine.id,
        timestamp=dt,
        image_path=s3_url,
        thumbnail_path=s3_url,
        source_window=source_window,
    )

    db.add(screenshot)
    db.commit()

    return {
        "status": "ok",
        "file": filename,
        "url": s3_url
    }