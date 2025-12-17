import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict


class EventBuffer:
    """Локальный SQLite буфер для событий"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_dir()
        self._init_db()
    
    def _ensure_dir(self):
        """Создать директорию если не существует"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
    
    def _init_db(self):
        """Инициализация таблицы"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    sent INTEGER DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sent ON events(sent)")
            conn.commit()
    
    def add(self, event: Dict):
        """Добавить событие в буфер"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO events (data, created_at) VALUES (?, ?)",
                (json.dumps(event), datetime.utcnow().isoformat())
            )
            conn.commit()
    
    def get_unsent(self, limit: int = 100) -> List[Dict]:
        """Получить неотправленные события"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT id, data FROM events WHERE sent = 0 ORDER BY id LIMIT ?",
                (limit,)
            )
            rows = cursor.fetchall()
            return [{"id": row[0], "data": json.loads(row[1])} for row in rows]
    
    def mark_sent(self, ids: List[int]):
        """Отметить события как отправленные"""
        if not ids:
            return
        with sqlite3.connect(self.db_path) as conn:
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"UPDATE events SET sent = 1 WHERE id IN ({placeholders})", ids)
            conn.commit()
    
    def cleanup_old(self, days: int = 7):
        """Удалить старые отправленные события"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                DELETE FROM events 
                WHERE sent = 1 
                AND datetime(created_at) < datetime('now', ?)
            """, (f"-{days} days",))
            conn.commit()
    
    def count_unsent(self) -> int:
        """Количество неотправленных событий"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM events WHERE sent = 0")
            return cursor.fetchone()[0]
