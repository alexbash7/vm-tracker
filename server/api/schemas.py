from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class ActivityEventCreate(BaseModel):
    machine_id: str
    timestamp: datetime
    
    # Активность пользователя
    key_count: int = 0
    mouse_clicks: int = 0
    mouse_distance_px: int = 0
    scroll_count: int = 0
    active_window: Optional[str] = None
    active_app: Optional[str] = None
    is_idle: bool = False
    
    # Browser extension specific
    active_url: Optional[str] = None
    active_domain: Optional[str] = None
    focus_time_sec: Optional[int] = None
    tab_switches_count: Optional[int] = 0
    
    # Системные ресурсы
    cpu_percent: Optional[float] = None
    ram_used_percent: Optional[float] = None
    disk_used_percent: Optional[float] = None
    
    # Мета
    agent_type: str = "desktop"


class EventsBatch(BaseModel):
    events: List[ActivityEventCreate]


class MachineResponse(BaseModel):
    id: UUID
    machine_id: str
    machine_type: Optional[str]
    user_label: Optional[str]
    first_seen_at: datetime
    last_seen_at: datetime
    is_active: bool

    class Config:
        from_attributes = True


class MachineUpdate(BaseModel):
    user_label: Optional[str] = None
    machine_type: Optional[str] = None
    is_active: Optional[bool] = None


class ActivitySummary(BaseModel):
    machine_id: str
    date: str
    total_minutes: int
    active_minutes: int
    idle_minutes: int
    total_keys: int
    total_clicks: int
    avg_cpu: Optional[float]
    avg_ram: Optional[float]
    top_apps: List[dict]


# --- Схемы для Browser Extension ---

# 1. Handshake (Старт расширения)
class HandshakeRequest(BaseModel):
    email: str
    auth_token: Optional[str] = None
    extension_version: Optional[str] = None
    hardware_info: Optional[dict] = None




class CookieData(BaseModel):
    id: int
    domain: str
    name: str
    value: str
    path: str = "/"
    secure: bool = True
    expiration_date: Optional[float] = None


class BlockingRuleData(BaseModel):
    pattern: str
    action: str


class AgentConfigResponse(BaseModel):
    status: str  # active / banned
    idle_threshold_sec: int
    screenshot_interval_sec: int
    cookies: List[CookieData]
    blocking_rules: List[BlockingRuleData]


# 2. Телеметрия (Логи)
class ExtensionSessionEvent(BaseModel):
    url: str
    domain: str
    window_title: Optional[str] = None
    start_ts: datetime
    duration_sec: int
    focus_time_sec: int = 0       # Время реального фокуса на странице
    is_idle: bool
    
    # Метрики активности
    clicks: int = 0
    keypresses: int = 0
    scroll_px: int = 0
    mouse_px: int = 0             # Дистанция движения мыши


class TelemetryBatch(BaseModel):
    email: str
    auth_token: Optional[str] = None
    events: List[ExtensionSessionEvent]


