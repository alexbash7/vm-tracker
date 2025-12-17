import os
import time


class SystemStats:
    def __init__(self):
        self._prev_cpu_times = None
    
    def _read_cpu_times(self):
        """Читаем CPU times из /proc/stat"""
        try:
            with open('/proc/stat') as f:
                line = f.readline()
            parts = line.split()[1:]  # cpu user nice system idle iowait irq softirq
            return list(map(int, parts[:7]))
        except:
            return None
    
    def get_cpu_percent(self):
        """Получить процент загрузки CPU"""
        current = self._read_cpu_times()
        if not current:
            return None
        
        if self._prev_cpu_times is None:
            self._prev_cpu_times = current
            time.sleep(0.1)
            current = self._read_cpu_times()
            if not current:
                return None
        
        prev = self._prev_cpu_times
        self._prev_cpu_times = current
        
        # Разница
        diff = [c - p for c, p in zip(current, prev)]
        total = sum(diff)
        if total == 0:
            return 0.0
        
        idle = diff[3]  # idle time
        cpu_percent = round((1 - idle / total) * 100, 1)
        return cpu_percent
    
    def get_ram_percent(self):
        """Получить процент использования RAM"""
        try:
            with open('/proc/meminfo') as f:
                lines = f.readlines()
            
            mem = {}
            for line in lines:
                parts = line.split()
                key = parts[0].rstrip(':')
                value = int(parts[1])
                mem[key] = value
            
            total = mem.get('MemTotal', 0)
            available = mem.get('MemAvailable', mem.get('MemFree', 0))
            
            if total == 0:
                return None
            
            used_percent = round((1 - available / total) * 100, 1)
            return used_percent
        except:
            return None
    
    def get_disk_percent(self):
        """Получить процент использования диска"""
        try:
            stat = os.statvfs('/')
            total = stat.f_blocks
            available = stat.f_bavail
            
            if total == 0:
                return None
            
            used_percent = round((1 - available / total) * 100, 1)
            return used_percent
        except:
            return None
    
    def get_all(self):
        """Получить все метрики"""
        return {
            "cpu_percent": self.get_cpu_percent(),
            "ram_used_percent": self.get_ram_percent(),
            "disk_used_percent": self.get_disk_percent()
        }
