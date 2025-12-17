import os
import yaml
import subprocess
from pathlib import Path


def get_machine_uuid():
    """Получить уникальный ID машины"""
    # Попробуем /etc/machine-id (Linux)
    machine_id_path = Path("/etc/machine-id")
    if machine_id_path.exists():
        return machine_id_path.read_text().strip()[:8]
    
    # Попробуем dmidecode
    try:
        result = subprocess.run(
            ["dmidecode", "-s", "system-uuid"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()[:8]
    except:
        pass
    
    # Генерируем случайный
    import uuid
    return str(uuid.uuid4())[:8]


def get_username():
    """Получить имя текущего пользователя"""
    return os.environ.get("USER", os.environ.get("USERNAME", "unknown"))


class Config:
    def __init__(self, config_path: str = None):
        self.config_path = config_path or self._find_config()
        self._load()
    
    def _find_config(self):
        """Поиск конфига в стандартных местах"""
        paths = [
            Path.home() / ".tracker.yaml",
            Path.home() / ".config" / "activity-tracker" / "config.yaml",
            Path("/etc/activity-tracker/config.yaml"),
            Path("config.yaml"),
        ]
        for p in paths:
            if p.exists():
                return str(p)
        return str(paths[0])  # default
    
    def _load(self):
        """Загрузить конфиг из файла или использовать defaults"""
        defaults = {
            "server_url": "http://localhost:8000",
            "machine_id": None,
            "user_label": None,
            "collect_interval_sec": 60,
            "send_interval_sec": 300,
            "buffer_path": "/var/lib/activity-tracker/buffer.db",
            "features": {
                "screenshots": False,
                "screenshots_interval_sec": 600,
                "track_system_stats": True
            }
        }
        
        config = defaults.copy()
        
        if os.path.exists(self.config_path):
            with open(self.config_path) as f:
                file_config = yaml.safe_load(f) or {}
                config.update(file_config)
        
        # Автогенерация machine_id если не указан
        if not config.get("machine_id"):
            machine_uuid = get_machine_uuid()
            username = get_username()
            config["machine_id"] = f"vm-{machine_uuid}-{username}"
        
        # Автогенерация user_label
        if not config.get("user_label"):
            config["user_label"] = config["machine_id"]
        
        self.server_url = config["server_url"]
        self.machine_id = config["machine_id"]
        self.user_label = config["user_label"]
        self.collect_interval_sec = config["collect_interval_sec"]
        self.send_interval_sec = config["send_interval_sec"]
        self.buffer_path = config["buffer_path"]
        self.features = config["features"]
    
    def save_generated_config(self):
        """Сохранить сгенерированный конфиг"""
        config_dir = Path(self.config_path).parent
        config_dir.mkdir(parents=True, exist_ok=True)
        
        config = {
            "server_url": self.server_url,
            "machine_id": self.machine_id,
            "user_label": self.user_label,
            "collect_interval_sec": self.collect_interval_sec,
            "send_interval_sec": self.send_interval_sec,
            "buffer_path": self.buffer_path,
            "features": self.features
        }
        
        with open(self.config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False)
