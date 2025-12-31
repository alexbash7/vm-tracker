from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, BigInteger, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from database import Base


class Machine(Base):
    __tablename__ = "machines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(String(255), unique=True, nullable=False, index=True)
    machine_type = Column(String(50))  # kasm, vps, local
    user_label = Column(String(255))  # человекочитаемое имя
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)

    events = relationship("ActivityEvent", back_populates="machine")
    screenshots = relationship("Screenshot", back_populates="machine")


class ActivityEvent(Base):
    __tablename__ = "activity_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    
    # Активность пользователя
    key_count = Column(Integer, default=0)
    mouse_clicks = Column(Integer, default=0)
    mouse_distance_px = Column(Integer, default=0)
    scroll_count = Column(Integer, default=0)
    active_window = Column(String(500))
    active_app = Column(String(255))
    is_idle = Column(Boolean, default=False)
    
    # Browser extension specific (NULL для desktop)
    active_url = Column(Text)
    active_domain = Column(String(255))
    tab_switches_count = Column(Integer)

    duration_seconds = Column(Integer, default=0, nullable=True)
    focus_time_sec = Column(Integer, default=0)
    
    # Системные ресурсы
    cpu_percent = Column(Float)
    ram_used_percent = Column(Float)
    disk_used_percent = Column(Float)
    
    # Мета
    agent_type = Column(String(50))  # desktop, browser_extension
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    machine = relationship("Machine", back_populates="events")


class Screenshot(Base):
    __tablename__ = "screenshots"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    image_path = Column(String(500))
    thumbnail_path = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    machine = relationship("Machine", back_populates="screenshots")


# Добавляем в models.py

class ExtensionProfile(Base):
    """
    Связывает email Google аккаунта с настройками.
    Может заменять или дополнять таблицу 'Machine'.
    """
    __tablename__ = "extension_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True) # test@useapps...
    google_sub_id = Column(String(255)) # Уникальный ID от Google OAuth
    
    # Настройки
    idle_threshold_sec = Column(Integer, default=60)
    screenshot_interval_sec = Column(Integer, default=300)
    is_active = Column(Boolean, default=True) # Kill switch

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    cookies = relationship("CookieVault", back_populates="profile")
    blocking_rules = relationship("BlockingRule", back_populates="profile")


class CookieVault(Base):
    """
    Хранилище кук, которые нужно инжектировать пользователю
    """
    __tablename__ = "cookie_vault"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("extension_profiles.id"), nullable=False)
    
    domain = Column(String(255), nullable=False) # .upwork.com
    name = Column(String(255), nullable=False)   # session_id
    value = Column(Text, nullable=False)         # само значение
    path = Column(String(255), default="/")
    secure = Column(Boolean, default=True)
    expiration_date = Column(Float, nullable=True) # Timestamp

    profile = relationship("ExtensionProfile", back_populates="cookies")


class BlockingRule(Base):
    """
    Правила блокировки URL (Regex)
    """
    __tablename__ = "blocking_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("extension_profiles.id"), nullable=True) # Null = глобальное правило
    
    pattern = Column(String(500), nullable=False) # youtube\.com\/shorts.*
    action = Column(String(50), default="block")
    
    profile = relationship("ExtensionProfile", back_populates="blocking_rules")