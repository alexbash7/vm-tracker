import subprocess
import threading
from typing import Optional


class MacOSActivityCollector:
    """Сбор активности пользователя на macOS"""
    
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
        """Получить название активного окна через AppleScript"""
        try:
            script = '''
            tell application "System Events"
                set frontApp to name of first application process whose frontmost is true
                tell process frontApp
                    try
                        return name of front window
                    on error
                        return frontApp
                    end try
                end tell
            end tell
            '''
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                return result.stdout.strip()[:500]
        except Exception as e:
            pass
        return None
    
    def get_active_app(self) -> Optional[str]:
        """Получить имя активного приложения через AppleScript"""
        try:
            script = '''
            tell application "System Events"
                return name of first application process whose frontmost is true
            end tell
            '''
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                return result.stdout.strip()[:255]
        except Exception as e:
            pass
        return None
    
    def get_idle_time_sec(self) -> int:
        """Получить время простоя через ioreg"""
        try:
            result = subprocess.run(
                ["ioreg", "-c", "IOHIDSystem"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'HIDIdleTime' in line:
                        # Значение в наносекундах
                        parts = line.split('=')
                        if len(parts) >= 2:
                            idle_ns = int(parts[1].strip())
                            return idle_ns // 1_000_000_000  # в секунды
        except Exception as e:
            pass
        return 0


class MacOSSystemStats:
    """Сбор системных метрик на macOS"""
    
    def __init__(self):
        self._prev_cpu_times = None
    
    def get_cpu_percent(self) -> Optional[float]:
        """Получить процент загрузки CPU через top"""
        try:
            result = subprocess.run(
                ["top", "-l", "1", "-n", "0", "-stats", "cpu"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'CPU usage' in line:
                        # "CPU usage: 5.26% user, 10.52% sys, 84.21% idle"
                        parts = line.split(',')
                        for part in parts:
                            if 'idle' in part:
                                idle_str = part.replace('idle', '').replace('%', '').strip()
                                idle = float(idle_str)
                                return round(100 - idle, 1)
        except Exception as e:
            pass
        return None
    
    def get_ram_percent(self) -> Optional[float]:
        """Получить процент использования RAM через vm_stat"""
        try:
            # Получаем размер страницы
            result = subprocess.run(
                ["sysctl", "-n", "hw.pagesize"],
                capture_output=True, text=True, timeout=2
            )
            page_size = int(result.stdout.strip())
            
            # Получаем статистику памяти
            result = subprocess.run(
                ["vm_stat"],
                capture_output=True, text=True, timeout=2
            )
            
            stats = {}
            for line in result.stdout.split('\n'):
                if ':' in line:
                    key, value = line.split(':')
                    # Убираем точку в конце числа
                    value = value.strip().rstrip('.')
                    try:
                        stats[key.strip()] = int(value)
                    except:
                        pass
            
            # Получаем общую память
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=2
            )
            total_mem = int(result.stdout.strip())
            
            # Считаем используемую память
            pages_free = stats.get('Pages free', 0)
            pages_inactive = stats.get('Pages inactive', 0)
            pages_speculative = stats.get('Pages speculative', 0)
            
            free_mem = (pages_free + pages_inactive + pages_speculative) * page_size
            used_percent = ((total_mem - free_mem) / total_mem) * 100
            
            return round(used_percent, 1)
        except Exception as e:
            pass
        return None
    
    def get_disk_percent(self) -> Optional[float]:
        """Получить процент использования диска"""
        try:
            result = subprocess.run(
                ["df", "-h", "/"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) >= 2:
                    parts = lines[1].split()
                    # Обычно 5-й столбец - процент использования
                    for part in parts:
                        if '%' in part:
                            return float(part.replace('%', ''))
        except Exception as e:
            pass
        return None
    
    def get_all(self):
        """Получить все метрики"""
        return {
            "cpu_percent": self.get_cpu_percent(),
            "ram_used_percent": self.get_ram_percent(),
            "disk_used_percent": self.get_disk_percent()
        }
