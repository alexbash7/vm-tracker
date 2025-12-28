#!/usr/bin/env python3
"""
Activity Tracker Agent
Собирает данные об активности пользователя и отправляет на сервер.
"""

import time
import signal
import sys
from datetime import datetime
from pathlib import Path

from config import Config
from buffer import EventBuffer
from sender import EventSender
from system_stats import SystemStats
from backends.linux import LinuxActivityCollector


class TrackerAgent:
    def __init__(self, config_path: str = None):
        self.config = Config(config_path)
        self.buffer = EventBuffer(self.config.buffer_path)
        self.sender = EventSender(self.config.server_url)
        self.system_stats = SystemStats()
        self.collector = LinuxActivityCollector()
        self._running = False
        self._last_send_time = 0
    
    def collect_event(self):
        """Собрать одно событие активности"""
        # Получаем данные от коллектора
        activity = self.collector.get_and_reset()
        
        # Получаем информацию об окне
        active_window = self.collector.get_active_window()
        active_app = self.collector.get_active_app()
        idle_time = self.collector.get_idle_time_sec()
        
        # Определяем idle (более 60 секунд без активности)
        is_idle = idle_time > 60 and activity["key_count"] == 0 and activity["mouse_clicks"] == 0
        
        # Системные ресурсы
        system = {}
        if self.config.features.get("track_system_stats", True):
            system = self.system_stats.get_all()
        
        event = {
            "machine_id": self.config.machine_id,
            "timestamp": datetime.utcnow().isoformat(),
            "key_count": activity["key_count"],
            "mouse_clicks": activity["mouse_clicks"],
            "mouse_distance_px": activity["mouse_distance_px"],
            "scroll_count": activity["scroll_count"],
            "active_window": active_window,
            "active_app": active_app,
            "is_idle": is_idle,
            "cpu_percent": system.get("cpu_percent"),
            "ram_used_percent": system.get("ram_used_percent"),
            "disk_used_percent": system.get("disk_used_percent"),
            "agent_type": "desktop"
        }
        
        return event
    
    def has_activity(self, event: dict) -> bool:
        """Проверить, есть ли реальная активность в событии"""
        return (
            event["key_count"] > 0 or
            event["mouse_clicks"] > 0 or
            event["scroll_count"] > 0 or
            event["mouse_distance_px"] > 0
        )
    
    def try_send_events(self):
        """Попытаться отправить накопленные события"""
        unsent = self.buffer.get_unsent(limit=100)
        if not unsent:
            return
        
        events = [item["data"] for item in unsent]
        ids = [item["id"] for item in unsent]
        
        if self.sender.send_batch(events):
            self.buffer.mark_sent(ids)
            print(f"Sent {len(events)} events")
        else:
            print(f"Failed to send {len(events)} events, will retry later")
    
    def run(self):
        """Основной цикл агента"""
        print(f"Starting Activity Tracker Agent")
        print(f"  Machine ID: {self.config.machine_id}")
        print(f"  Server: {self.config.server_url}")
        print(f"  Collect interval: {self.config.collect_interval_sec}s")
        print(f"  Send interval: {self.config.send_interval_sec}s")
        
        # Запускаем слушатели
        if not self.collector.start():
            print("Warning: Could not start input listeners, activity tracking limited")
        
        self._running = True
        self._last_send_time = time.time()
        
        # Обработка сигналов для graceful shutdown
        def signal_handler(sig, frame):
            print("\nShutting down...")
            self._running = False
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        try:
            while self._running:
                # Собираем событие
                event = self.collect_event()
                
                # Добавляем в буфер только если есть активность
                if self.has_activity(event):
                    self.buffer.add(event)
                
                # Проверяем нужно ли отправлять
                now = time.time()
                if now - self._last_send_time >= self.config.send_interval_sec:
                    self.try_send_events()
                    self._last_send_time = now
                    
                    # Очистка старых событий раз в день
                    self.buffer.cleanup_old(days=7)
                
                # Ждём до следующего сбора
                time.sleep(self.config.collect_interval_sec)
        
        finally:
            # Финальная отправка при выходе
            print("Sending remaining events...")
            self.try_send_events()
            self.collector.stop()
            print("Agent stopped")


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    agent = TrackerAgent(config_path)
    agent.run()


if __name__ == "__main__":
    main()
