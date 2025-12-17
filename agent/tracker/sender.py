import requests
from typing import List, Dict


class EventSender:
    """Отправка событий на сервер"""
    
    def __init__(self, server_url: str, timeout: int = 30):
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
    
    def send_batch(self, events: List[Dict]) -> bool:
        """Отправить пачку событий"""
        if not events:
            return True
        
        try:
            response = requests.post(
                f"{self.server_url}/api/events",
                json={"events": events},
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                return True
            else:
                print(f"Server returned {response.status_code}: {response.text}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"Failed to send events: {e}")
            return False
    
    def check_health(self) -> bool:
        """Проверить доступность сервера"""
        try:
            response = requests.get(
                f"{self.server_url}/health",
                timeout=5
            )
            return response.status_code == 200
        except:
            return False
