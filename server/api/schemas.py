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
    tab_switches_count: Optional[int] = None
    
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
