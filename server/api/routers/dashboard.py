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

# Допустимые интервалы в минутах
ALLOWED_INTERVALS = [5, 10, 15, 30, 60]


def get_interval_data(db: Session, machine_id: str, target_date: date, interval_minutes: int = 60):
    """Получить данные по интервалам для машины за день"""
    
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
    
    # Количество интервалов в сутках
    intervals_per_day = (24 * 60) // interval_minutes
    
    # Инициализация по интервалам
    intervals_data = {i: {
        'keys': 0, 'clicks': 0, 'distance': 0, 'scroll': 0,
        'cpu_sum': 0, 'ram_sum': 0, 'cpu_count': 0, 'ram_count': 0,
        'active_minutes': 0
    } for i in range(intervals_per_day)}
    
    total_keys = 0
    total_clicks = 0
    total_scroll = 0
    total_distance = 0
    active_minutes = 0
    
    for event in events:
        # Вычисляем индекс интервала
        minutes_from_midnight = event.timestamp.hour * 60 + event.timestamp.minute
        interval_index = minutes_from_midnight // interval_minutes
        
        if interval_index >= intervals_per_day:
            interval_index = intervals_per_day - 1
        
        intervals_data[interval_index]['keys'] += event.key_count or 0
        intervals_data[interval_index]['clicks'] += event.mouse_clicks or 0
        intervals_data[interval_index]['distance'] += event.mouse_distance_px or 0
        intervals_data[interval_index]['scroll'] += event.scroll_count or 0
        
        total_keys += event.key_count or 0
        total_clicks += event.mouse_clicks or 0
        total_scroll += event.scroll_count or 0
        total_distance += event.mouse_distance_px or 0
        
        # Считаем активные минуты (события с какой-либо активностью)
        has_activity = (event.key_count or 0) > 0 or (event.mouse_clicks or 0) > 0 or (event.scroll_count or 0) > 0 or (event.mouse_distance_px or 0) > 0
        if has_activity:
            active_minutes += 1
            intervals_data[interval_index]['active_minutes'] += 1
        
        # CPU/RAM только если была активность
        if has_activity:
            if event.cpu_percent is not None:
                intervals_data[interval_index]['cpu_sum'] += event.cpu_percent
                intervals_data[interval_index]['cpu_count'] += 1
            if event.ram_used_percent is not None:
                intervals_data[interval_index]['ram_sum'] += event.ram_used_percent
                intervals_data[interval_index]['ram_count'] += 1
    
    # Формируем лейблы для интервалов
    labels = []
    for i in range(intervals_per_day):
        total_minutes = i * interval_minutes
        hour = total_minutes // 60
        minute = total_minutes % 60
        labels.append(f"{hour:02d}:{minute:02d}")
    
    keys = [intervals_data[i]['keys'] for i in range(intervals_per_day)]
    clicks = [intervals_data[i]['clicks'] for i in range(intervals_per_day)]
    distance = [intervals_data[i]['distance'] for i in range(intervals_per_day)]
    scroll = [intervals_data[i]['scroll'] for i in range(intervals_per_day)]
    
    # CPU/RAM - среднее только за активные минуты
    cpu = []
    ram = []
    for i in range(intervals_per_day):
        if intervals_data[i]['cpu_count'] > 0:
            cpu.append(round(intervals_data[i]['cpu_sum'] / intervals_data[i]['cpu_count'], 1))
        else:
            cpu.append(0)
        if intervals_data[i]['ram_count'] > 0:
            ram.append(round(intervals_data[i]['ram_sum'] / intervals_data[i]['ram_count'], 1))
        else:
            ram.append(0)
    
    # Считаем активные часы (интервалы где была хоть какая-то активность)
    active_intervals = sum(1 for i in range(intervals_per_day) if intervals_data[i]['keys'] > 0 or intervals_data[i]['clicks'] > 0)
    
    has_resources = any(c > 0 for c in cpu) or any(r > 0 for r in ram)
    
    # Форматируем active time как "Xh Ym"
    active_hours = active_minutes // 60
    active_mins_remainder = active_minutes % 60
    active_time_formatted = f"{active_hours}h {active_mins_remainder}m"
    
    # Средние значения per minute (только если есть активные минуты)
    avg_keys_per_min = round(total_keys / active_minutes, 1) if active_minutes > 0 else 0
    avg_clicks_per_min = round(total_clicks / active_minutes, 1) if active_minutes > 0 else 0
    avg_scroll_per_min = round(total_scroll / active_minutes, 1) if active_minutes > 0 else 0
    avg_distance_per_min = round(total_distance / active_minutes, 1) if active_minutes > 0 else 0
    
    return {
        'machine_id': machine_id,
        'label': machine.user_label or machine_id,
        'total_keys': total_keys,
        'total_clicks': total_clicks,
        'total_scroll': total_scroll,
        'total_distance': total_distance,
        'active_minutes': active_minutes,
        'active_time_formatted': active_time_formatted,
        'avg_keys_per_min': avg_keys_per_min,
        'avg_clicks_per_min': avg_clicks_per_min,
        'avg_scroll_per_min': avg_scroll_per_min,
        'avg_distance_per_min': avg_distance_per_min,
        'has_resources': has_resources,
        'chart': {
            'labels': labels,
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
    interval: int = 60,
    db: Session = Depends(get_db)
):
    """Страница дневных графиков"""
    
    # Валидация интервала
    if interval not in ALLOWED_INTERVALS:
        interval = 60
    
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
            machine_data = get_interval_data(db, m.machine_id, target_date, interval)
            if machine_data:
                data.append(machine_data)
                chart_data.append(machine_data['chart'])
    else:
        # Одна машина
        machine_data = get_interval_data(db, machine, target_date, interval)
        if machine_data:
            data.append(machine_data)
            chart_data.append(machine_data['chart'])
    
    return templates.TemplateResponse("daily.html", {
        "request": request,
        "current_date": target_date.isoformat(),
        "selected_machine": machine,
        "selected_interval": interval,
        "allowed_intervals": ALLOWED_INTERVALS,
        "machines": all_machines,
        "data": data,
        "chart_data": chart_data
    })
