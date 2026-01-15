from fastapi import APIRouter, Depends
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
