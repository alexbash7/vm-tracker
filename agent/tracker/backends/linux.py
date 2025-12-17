import subprocess
import threading
from typing import Optional


class LinuxActivityCollector:
    """Сбор активности пользователя на Linux (X11)"""
    
    def __init__(self):
        self.key_count = 0
        self.mouse_clicks = 0
        self.mouse_distance = 0
        self.scroll_count = 0
        self._last_mouse_pos = None
        self._lock = threading.Lock()
        self._listener_keyboard = None
        self._listener_mouse = None
        self._running = False
    
    def start(self):
        """Запустить слушатели событий"""
        try:
            from pynput import keyboard, mouse
            
            self._running = True
            
            # Keyboard listener
            def on_key_press(key):
                with self._lock:
                    self.key_count += 1
            
            self._listener_keyboard = keyboard.Listener(on_press=on_key_press)
            self._listener_keyboard.start()
            
            # Mouse listener
            def on_click(x, y, button, pressed):
                if pressed:
                    with self._lock:
                        self.mouse_clicks += 1
            
            def on_move(x, y):
                with self._lock:
                    if self._last_mouse_pos:
                        dx = abs(x - self._last_mouse_pos[0])
                        dy = abs(y - self._last_mouse_pos[1])
                        self.mouse_distance += int((dx**2 + dy**2)**0.5)
                    self._last_mouse_pos = (x, y)
            
            def on_scroll(x, y, dx, dy):
                with self._lock:
                    self.scroll_count += 1
            
            self._listener_mouse = mouse.Listener(
                on_click=on_click,
                on_move=on_move,
                on_scroll=on_scroll
            )
            self._listener_mouse.start()
            
            return True
        except Exception as e:
            print(f"Failed to start listeners: {e}")
            return False
    
    def stop(self):
        """Остановить слушатели"""
        self._running = False
        if self._listener_keyboard:
            self._listener_keyboard.stop()
        if self._listener_mouse:
            self._listener_mouse.stop()
    
    def get_and_reset(self):
        """Получить накопленные данные и сбросить счётчики"""
        with self._lock:
            data = {
                "key_count": self.key_count,
                "mouse_clicks": self.mouse_clicks,
                "mouse_distance_px": self.mouse_distance,
                "scroll_count": self.scroll_count,
            }
            self.key_count = 0
            self.mouse_clicks = 0
            self.mouse_distance = 0
            self.scroll_count = 0
            return data
    
    def get_active_window(self) -> Optional[str]:
        """Получить название активного окна через xdotool"""
        try:
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                return result.stdout.strip()[:500]
        except:
            pass
        return None
    
    def get_active_app(self) -> Optional[str]:
        """Получить имя активного приложения"""
        try:
            # Получаем PID активного окна
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowpid"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode != 0:
                return None
            
            pid = result.stdout.strip()
            
            # Получаем имя процесса
            result = subprocess.run(
                ["ps", "-p", pid, "-o", "comm="],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                return result.stdout.strip()[:255]
        except:
            pass
        return None
    
    def get_idle_time_sec(self) -> int:
        """Получить время простоя через xprintidle"""
        try:
            result = subprocess.run(
                ["xprintidle"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                # xprintidle возвращает миллисекунды
                return int(result.stdout.strip()) // 1000
        except:
            pass
        return 0
