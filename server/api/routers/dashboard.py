from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date, timedelta
from typing import Optional
import os

from database import get_db
from models import Machine, ActivityEvent

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Templates
templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
templates = Jinja2Templates(directory=templates_dir)


def get_hourly_data(db: Session, machine_id: str, target_date: date):
    """Получить данные по часам для машины за день"""
    
    machine = db.query(Machine).filter(Machine.machine_id == machine_id).first()
    if not machine:
        return None
    
    start = datetime.combine(target_date, datetime.min.time())
    end = datetime.combine(target_date, datetime.max.time())
    
    events = db.query(ActivityEvent).filter(
        ActivityEvent.machine_id == machine.id,
        ActivityEvent.timestamp >= start,
        ActivityEvent.timestamp <= end
    ).all()
    
    if not events:
        return None
    
    # Инициализация по часам
    hours_data = {h: {
        'keys': 0, 'clicks': 0, 'distance': 0, 'scroll': 0,
        'cpu_sum': 0, 'ram_sum': 0, 'cpu_count': 0, 'ram_count': 0
    } for h in range(24)}
    
    total_keys = 0
    total_clicks = 0
    total_scroll = 0
    active_minutes = 0
    
    for event in events:
        hour = event.timestamp.hour
        
        hours_data[hour]['keys'] += event.key_count or 0
        hours_data[hour]['clicks'] += event.mouse_clicks or 0
        hours_data[hour]['distance'] += event.mouse_distance_px or 0
        hours_data[hour]['scroll'] += event.scroll_count or 0
        
        total_keys += event.key_count or 0
        total_clicks += event.mouse_clicks or 0
        total_scroll += event.scroll_count or 0
        
        if not event.is_idle:
            active_minutes += 1
        
        # CPU/RAM только если была активность
        has_activity = (event.key_count or 0) > 0 or (event.mouse_clicks or 0) > 0
        if has_activity:
            if event.cpu_percent is not None:
                hours_data[hour]['cpu_sum'] += event.cpu_percent
                hours_data[hour]['cpu_count'] += 1
            if event.ram_used_percent is not None:
                hours_data[hour]['ram_sum'] += event.ram_used_percent
                hours_data[hour]['ram_count'] += 1
    
    # Формируем данные для графиков
    hours = [f"{h:02d}:00" for h in range(24)]
    keys = [hours_data[h]['keys'] for h in range(24)]
    clicks = [hours_data[h]['clicks'] for h in range(24)]
    distance = [hours_data[h]['distance'] for h in range(24)]
    scroll = [hours_data[h]['scroll'] for h in range(24)]
    
    # CPU/RAM - среднее только за активные минуты, 0 если не было активности
    cpu = []
    ram = []
    for h in range(24):
        if hours_data[h]['cpu_count'] > 0:
            cpu.append(round(hours_data[h]['cpu_sum'] / hours_data[h]['cpu_count'], 1))
        else:
            cpu.append(0)
        if hours_data[h]['ram_count'] > 0:
            ram.append(round(hours_data[h]['ram_sum'] / hours_data[h]['ram_count'], 1))
        else:
            ram.append(0)
    
    # Считаем активные часы (часы где была хоть какая-то активность)
    active_hours = sum(1 for h in range(24) if hours_data[h]['keys'] > 0 or hours_data[h]['clicks'] > 0)
    
    has_resources = any(c > 0 for c in cpu) or any(r > 0 for r in ram)
    
    return {
        'machine_id': machine_id,
        'label': machine.user_label or machine_id,
        'total_keys': total_keys,
        'total_clicks': total_clicks,
        'total_scroll': total_scroll,
        'active_hours': active_hours,
        'active_minutes': active_minutes,
        'has_resources': has_resources,
        'chart': {
            'hours': hours,
            'keys': keys,
            'clicks': clicks,
            'distance': distance,
            'scroll': scroll,
            'cpu': cpu,
            'ram': ram
        }
    }


@router.get("/daily", response_class=HTMLResponse)
async def daily_dashboard(
    request: Request,
    date: Optional[str] = None,
    machine: str = "all",
    db: Session = Depends(get_db)
):
    """Страница дневных графиков"""
    
    # Дата по умолчанию - сегодня
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        except:
            target_date = datetime.utcnow().date()
    else:
        target_date = datetime.utcnow().date()
    
    # Получаем список всех машин для sidebar
    all_machines = db.query(Machine).order_by(Machine.user_label).all()
    
    # Получаем данные
    data = []
    chart_data = []
    
    if machine == "all":
        # Все машины
        for m in all_machines:
            machine_data = get_hourly_data(db, m.machine_id, target_date)
            if machine_data:
                data.append(machine_data)
                chart_data.append(machine_data['chart'])
    else:
        # Одна машина
        machine_data = get_hourly_data(db, machine, target_date)
        if machine_data:
            data.append(machine_data)
            chart_data.append(machine_data['chart'])
    
    return templates.TemplateResponse("daily.html", {
        "request": request,
        "current_date": target_date.isoformat(),
        "selected_machine": machine,
        "machines": all_machines,
        "data": data,
        "chart_data": chart_data
    })
