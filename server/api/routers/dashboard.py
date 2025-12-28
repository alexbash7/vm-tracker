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


@router.get("/weekly", response_class=HTMLResponse)
async def weekly_dashboard(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    machine: str = "all",
    db: Session = Depends(get_db)
):
    """Страница недельных/периодных данных"""
    
    # Определяем диапазон дат
    today = datetime.utcnow().date()
    
    if start and end:
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d").date()
            end_date = datetime.strptime(end, "%Y-%m-%d").date()
        except:
            # Fallback на текущую неделю
            start_date = today - timedelta(days=today.weekday())
            end_date = start_date + timedelta(days=6)
    else:
        # По умолчанию — текущая неделя (Пн-Вс)
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
    
    # Получаем список всех машин для sidebar
    all_machines = db.query(Machine).order_by(Machine.user_label).all()
    
    # Собираем данные по дням для каждой машины
    data = []
    
    machines_to_process = all_machines if machine == "all" else [
        m for m in all_machines if m.machine_id == machine
    ]
    
    for m in machines_to_process:
        machine_data = get_period_data(db, m.machine_id, start_date, end_date)
        if machine_data:
            data.append(machine_data)
    
    # Генерируем список дней для заголовков
    days = []
    current = start_date
    while current <= end_date:
        days.append({
            'date': current.isoformat(),
            'label': current.strftime('%a %d.%m'),  # "Mon 23.12"
        })
        current += timedelta(days=1)
    
    return templates.TemplateResponse("weekly.html", {
        "request": request,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "selected_machine": machine,
        "machines": all_machines,
        "data": data,
        "days": days
    })


def get_period_data(db: Session, machine_id: str, start_date: date, end_date: date):
    """Получить данные по дням для машины за период"""
    
    machine = db.query(Machine).filter(Machine.machine_id == machine_id).first()
    if not machine:
        return None
    
    start = datetime.combine(start_date, datetime.min.time())
    end = datetime.combine(end_date, datetime.max.time())
    
    events = db.query(ActivityEvent).filter(
        ActivityEvent.machine_id == machine.id,
        ActivityEvent.timestamp >= start,
        ActivityEvent.timestamp <= end
    ).all()
    
    if not events:
        return None
    
    # Группируем по дням
    days_data = {}
    current = start_date
    while current <= end_date:
        days_data[current.isoformat()] = {
            'total_keys': 0,
            'total_clicks': 0,
            'total_scroll': 0,
            'total_distance': 0,
            'active_minutes': 0,
            'cpu_sum': 0,
            'cpu_count': 0,
            'ram_sum': 0,
            'ram_count': 0,
        }
        current += timedelta(days=1)
    
    for event in events:
        day_key = event.timestamp.date().isoformat()
        if day_key not in days_data:
            continue
        
        days_data[day_key]['total_keys'] += event.key_count or 0
        days_data[day_key]['total_clicks'] += event.mouse_clicks or 0
        days_data[day_key]['total_scroll'] += event.scroll_count or 0
        days_data[day_key]['total_distance'] += event.mouse_distance_px or 0
        
        # Считаем активные минуты
        has_activity = (event.key_count or 0) > 0 or (event.mouse_clicks or 0) > 0 or (event.scroll_count or 0) > 0 or (event.mouse_distance_px or 0) > 0
        if has_activity:
            days_data[day_key]['active_minutes'] += 1
            
            if event.cpu_percent is not None:
                days_data[day_key]['cpu_sum'] += event.cpu_percent
                days_data[day_key]['cpu_count'] += 1
            if event.ram_used_percent is not None:
                days_data[day_key]['ram_sum'] += event.ram_used_percent
                days_data[day_key]['ram_count'] += 1
    
    # Формируем итоговые данные по дням
    daily_stats = []
    current = start_date
    while current <= end_date:
        day_key = current.isoformat()
        d = days_data[day_key]
        
        active_mins = d['active_minutes']
        
        # Форматируем время
        hours = active_mins // 60
        mins = active_mins % 60
        active_time = f"{hours}h {mins}m"
        
        # Средние значения
        avg_keys = round(d['total_keys'] / active_mins, 1) if active_mins > 0 else 0
        avg_clicks = round(d['total_clicks'] / active_mins, 1) if active_mins > 0 else 0
        avg_scroll = round(d['total_scroll'] / active_mins, 1) if active_mins > 0 else 0
        avg_distance = round(d['total_distance'] / active_mins, 1) if active_mins > 0 else 0
        avg_cpu = round(d['cpu_sum'] / d['cpu_count'], 1) if d['cpu_count'] > 0 else 0
        avg_ram = round(d['ram_sum'] / d['ram_count'], 1) if d['ram_count'] > 0 else 0
        
        daily_stats.append({
            'date': day_key,
            'total_keys': d['total_keys'],
            'total_clicks': d['total_clicks'],
            'total_scroll': d['total_scroll'],
            'total_distance': d['total_distance'],
            'active_time': active_time,
            'active_minutes': active_mins,
            'avg_keys': avg_keys,
            'avg_clicks': avg_clicks,
            'avg_scroll': avg_scroll,
            'avg_distance': avg_distance,
            'avg_cpu': avg_cpu,
            'avg_ram': avg_ram,
        })
        
        current += timedelta(days=1)
    
    return {
        'machine_id': machine_id,
        'label': machine.user_label or machine_id,
        'daily_stats': daily_stats
    }
