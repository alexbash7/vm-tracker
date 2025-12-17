from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional
from datetime import datetime, timedelta, date

from database import get_db
from models import Machine, ActivityEvent
from schemas import ActivitySummary

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("/{machine_id}/events")
async def get_events(
    machine_id: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: int = Query(default=1000, le=10000),
    db: Session = Depends(get_db)
):
    """Получить сырые события для машины"""
    machine = db.query(Machine).filter(Machine.machine_id == machine_id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    
    query = db.query(ActivityEvent).filter(ActivityEvent.machine_id == machine.id)
    
    if start:
        query = query.filter(ActivityEvent.timestamp >= start)
    if end:
        query = query.filter(ActivityEvent.timestamp <= end)
    
    events = query.order_by(desc(ActivityEvent.timestamp)).limit(limit).all()
    
    return {
        "machine_id": machine_id,
        "count": len(events),
        "events": [
            {
                "timestamp": e.timestamp.isoformat(),
                "key_count": e.key_count,
                "mouse_clicks": e.mouse_clicks,
                "mouse_distance_px": e.mouse_distance_px,
                "scroll_count": e.scroll_count,
                "active_window": e.active_window,
                "active_app": e.active_app,
                "is_idle": e.is_idle,
                "cpu_percent": e.cpu_percent,
                "ram_used_percent": e.ram_used_percent,
                "disk_used_percent": e.disk_used_percent
            }
            for e in events
        ]
    }


@router.get("/{machine_id}/summary")
async def get_summary(
    machine_id: str,
    date_str: Optional[str] = None,  # YYYY-MM-DD
    db: Session = Depends(get_db)
):
    """Получить суммарную статистику за день"""
    machine = db.query(Machine).filter(Machine.machine_id == machine_id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    
    # По умолчанию - сегодня
    if date_str:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        target_date = date.today()
    
    start = datetime.combine(target_date, datetime.min.time())
    end = datetime.combine(target_date, datetime.max.time())
    
    events = db.query(ActivityEvent).filter(
        ActivityEvent.machine_id == machine.id,
        ActivityEvent.timestamp >= start,
        ActivityEvent.timestamp <= end
    ).all()
    
    if not events:
        return {
            "machine_id": machine_id,
            "date": target_date.isoformat(),
            "total_minutes": 0,
            "active_minutes": 0,
            "idle_minutes": 0,
            "total_keys": 0,
            "total_clicks": 0,
            "avg_cpu": None,
            "avg_ram": None,
            "top_apps": []
        }
    
    total_minutes = len(events)
    active_minutes = sum(1 for e in events if not e.is_idle)
    idle_minutes = total_minutes - active_minutes
    total_keys = sum(e.key_count or 0 for e in events)
    total_clicks = sum(e.mouse_clicks or 0 for e in events)
    
    cpu_values = [e.cpu_percent for e in events if e.cpu_percent is not None]
    ram_values = [e.ram_used_percent for e in events if e.ram_used_percent is not None]
    
    avg_cpu = round(sum(cpu_values) / len(cpu_values), 1) if cpu_values else None
    avg_ram = round(sum(ram_values) / len(ram_values), 1) if ram_values else None
    
    # Топ приложений по времени
    app_minutes = {}
    for e in events:
        app = e.active_app or "Unknown"
        app_minutes[app] = app_minutes.get(app, 0) + 1
    
    top_apps = sorted(app_minutes.items(), key=lambda x: x[1], reverse=True)[:10]
    top_apps = [{"app": app, "minutes": mins} for app, mins in top_apps]
    
    return {
        "machine_id": machine_id,
        "date": target_date.isoformat(),
        "total_minutes": total_minutes,
        "active_minutes": active_minutes,
        "idle_minutes": idle_minutes,
        "total_keys": total_keys,
        "total_clicks": total_clicks,
        "avg_cpu": avg_cpu,
        "avg_ram": avg_ram,
        "top_apps": top_apps
    }


@router.get("/{machine_id}/timeline")
async def get_timeline(
    machine_id: str,
    date_str: Optional[str] = None,  # YYYY-MM-DD
    db: Session = Depends(get_db)
):
    """Получить таймлайн активности по часам для heatmap"""
    machine = db.query(Machine).filter(Machine.machine_id == machine_id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    
    if date_str:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        target_date = date.today()
    
    start = datetime.combine(target_date, datetime.min.time())
    end = datetime.combine(target_date, datetime.max.time())
    
    events = db.query(ActivityEvent).filter(
        ActivityEvent.machine_id == machine.id,
        ActivityEvent.timestamp >= start,
        ActivityEvent.timestamp <= end
    ).all()
    
    # Группируем по часам
    hours = {h: {"active": 0, "idle": 0, "total": 0} for h in range(24)}
    
    for e in events:
        hour = e.timestamp.hour
        hours[hour]["total"] += 1
        if e.is_idle:
            hours[hour]["idle"] += 1
        else:
            hours[hour]["active"] += 1
    
    return {
        "machine_id": machine_id,
        "date": target_date.isoformat(),
        "hours": hours
    }
