#!/usr/bin/env python3
"""
Генерация тестовых данных для Activity Tracker
Запуск: python seed_data.py
"""

import random
from datetime import datetime, timedelta
from database import SessionLocal, engine
from models import Base, Machine, ActivityEvent

# Создаём таблицы если не существуют
Base.metadata.create_all(bind=engine)


def generate_activity_pattern(hour: int, worker_type: str) -> dict:
    """Генерирует паттерн активности в зависимости от часа и типа работника"""
    
    # Базовые рабочие часы
    if hour < 8 or hour > 20:
        return None  # Не работает
    
    if worker_type == "active":
        # Активный работник: 9-18, перерыв 13-14
        if hour < 9 or hour > 18:
            return None
        if hour == 13:  # Обед
            return None
        
        return {
            "key_count": random.randint(80, 200),
            "mouse_clicks": random.randint(30, 80),
            "mouse_distance_px": random.randint(8000, 20000),
            "scroll_count": random.randint(50, 150),
            "cpu_percent": random.uniform(15, 45),
            "ram_used_percent": random.uniform(50, 75),
        }
    
    elif worker_type == "medium":
        # Средний работник: 10-17, часто отвлекается
        if hour < 10 or hour > 17:
            return None
        if hour in [12, 15]:  # Перерывы
            return None
        
        return {
            "key_count": random.randint(40, 120),
            "mouse_clicks": random.randint(15, 50),
            "mouse_distance_px": random.randint(4000, 12000),
            "scroll_count": random.randint(20, 80),
            "cpu_percent": random.uniform(10, 35),
            "ram_used_percent": random.uniform(45, 65),
        }
    
    elif worker_type == "lazy":
        # Мало работает: 11-16, много idle
        if hour < 11 or hour > 16:
            return None
        if random.random() < 0.3:  # 30% времени idle
            return None
        
        return {
            "key_count": random.randint(10, 50),
            "mouse_clicks": random.randint(5, 25),
            "mouse_distance_px": random.randint(1000, 5000),
            "scroll_count": random.randint(5, 30),
            "cpu_percent": random.uniform(5, 25),
            "ram_used_percent": random.uniform(40, 55),
        }
    
    return None


def seed_data():
    db = SessionLocal()
    
    try:
        # Очищаем старые тестовые данные
        db.query(ActivityEvent).filter(
            ActivityEvent.machine_id.in_(
                db.query(Machine.id).filter(Machine.machine_id.like("vm-seed-%"))
            )
        ).delete(synchronize_session=False)
        db.query(Machine).filter(Machine.machine_id.like("vm-seed-%")).delete()
        db.commit()
        
        # Создаём машины
        machines_config = [
            ("vm-seed-01-alice", "Alice (активная)", "active"),
            ("vm-seed-01-bob", "Bob (средний)", "medium"),
            ("vm-seed-01-charlie", "Charlie (слабый)", "lazy"),
        ]
        
        machines = []
        for machine_id, label, worker_type in machines_config:
            machine = Machine(
                machine_id=machine_id,
                user_label=label,
                machine_type="vps",
                is_active=True
            )
            db.add(machine)
            db.commit()
            db.refresh(machine)
            machines.append((machine, worker_type))
            print(f"Created machine: {machine_id} ({label})")
        
        # Генерируем данные за последние 7 дней
        now = datetime.utcnow()
        apps = ["chrome", "vscode", "terminal", "slack", "figma"]
        windows = [
            "Google Chrome - Project Tasks",
            "VS Code - main.py",
            "Terminal - ssh server",
            "Slack - Team Chat",
            "Figma - Design v2"
        ]
        
        total_events = 0
        
        for day_offset in range(7, 0, -1):
            day = now - timedelta(days=day_offset)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            
            for machine, worker_type in machines:
                # Каждую минуту в течение дня (но только рабочие часы)
                for hour in range(24):
                    pattern = generate_activity_pattern(hour, worker_type)
                    if pattern is None:
                        continue
                    
                    # Генерируем записи для каждой минуты часа (но не все)
                    minutes_active = random.randint(40, 58)  # 40-58 минут из 60
                    
                    for minute in random.sample(range(60), minutes_active):
                        timestamp = day_start + timedelta(hours=hour, minutes=minute)
                        
                        # Добавляем вариативность к базовому паттерну
                        variation = random.uniform(0.7, 1.3)
                        
                        is_idle = random.random() < 0.1  # 10% idle
                        
                        event = ActivityEvent(
                            machine_id=machine.id,
                            timestamp=timestamp,
                            key_count=int(pattern["key_count"] * variation / 60) if not is_idle else 0,
                            mouse_clicks=int(pattern["mouse_clicks"] * variation / 60) if not is_idle else 0,
                            mouse_distance_px=int(pattern["mouse_distance_px"] * variation / 60) if not is_idle else 0,
                            scroll_count=int(pattern["scroll_count"] * variation / 60) if not is_idle else 0,
                            active_window=random.choice(windows) if not is_idle else None,
                            active_app=random.choice(apps) if not is_idle else None,
                            is_idle=is_idle,
                            cpu_percent=round(pattern["cpu_percent"] * random.uniform(0.8, 1.2), 1),
                            ram_used_percent=round(pattern["ram_used_percent"] * random.uniform(0.95, 1.05), 1),
                            disk_used_percent=round(random.uniform(45, 55), 1),
                            agent_type="desktop"
                        )
                        db.add(event)
                        total_events += 1
                
                # Коммитим после каждого дня для каждой машины
                db.commit()
            
            print(f"Generated data for {day_start.date()}")
        
        print(f"\nTotal events created: {total_events}")
        print("Seed data complete!")
        
    finally:
        db.close()


if __name__ == "__main__":
    seed_data()
