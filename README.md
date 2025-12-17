# Activity Tracker

Система отслеживания активности пользователей на удалённых рабочих станциях.

## Компоненты

```
┌─────────────────────────────────────────┐
│           Server (CapRover)             │
│  ┌──────────┐  ┌─────────┐              │
│  │ Postgres │◄─│   API   │              │
│  └──────────┘  └────▲────┘              │
└─────────────────────┼───────────────────┘
                      │ HTTPS
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   ┌─────────┐  ┌───────────┐  ┌─────────┐
   │ VPS     │  │ Multi-user│  │ Local   │
   │ Single  │  │ VPS (xrdp)│  │ Machine │
   │ user    │  │ N users   │  │         │
   └─────────┘  └───────────┘  └─────────┘
```

## Быстрый старт

### 1. Деплой API на сервер

```bash
cd server
docker-compose up -d
```

API будет доступен на порту 8100.

### 2. Установка агента на VPS (один пользователь)

```bash
cd deploy
sudo ./single-user-vps.sh https://tracker-api.your-domain.com
```

### 3. Multi-user VPS с xrdp

```bash
cd deploy
sudo ./multi-user-vps.sh 3 https://tracker-api.your-domain.com
```

Создаст 3 пользователей (user1, user2, user3) с RDP доступом.

## API Endpoints

### Приём данных

```
POST /api/events
{
  "events": [
    {
      "machine_id": "vm-abc123-user1",
      "timestamp": "2024-01-15T10:30:00Z",
      "key_count": 150,
      "mouse_clicks": 45,
      "mouse_distance_px": 12500,
      "scroll_count": 20,
      "active_window": "Visual Studio Code",
      "active_app": "code",
      "is_idle": false,
      "cpu_percent": 25.5,
      "ram_used_percent": 68.2,
      "disk_used_percent": 45.0
    }
  ]
}
```

### Получение данных

```
GET /api/machines                     # Список всех машин
GET /api/machines/{machine_id}        # Информация о машине
PATCH /api/machines/{machine_id}      # Обновить (например, user_label)

GET /api/activity/{machine_id}/events?start=...&end=...  # Сырые события
GET /api/activity/{machine_id}/summary?date=2024-01-15   # Суммарная статистика
GET /api/activity/{machine_id}/timeline?date=2024-01-15  # Таймлайн по часам
```

## Конфигурация агента

`~/.config/activity-tracker/config.yaml`:

```yaml
server_url: "https://tracker-api.your-domain.com"
machine_id: "vm-abc123-user1"  # автогенерируется если не указан
collect_interval_sec: 60        # сбор каждую минуту
send_interval_sec: 300          # отправка раз в 5 минут
buffer_path: "~/.local/share/activity-tracker/buffer.db"
features:
  screenshots: false
  track_system_stats: true
```

## Метрики

Агент собирает каждую минуту:

| Метрика | Описание |
|---------|----------|
| key_count | Количество нажатий клавиш |
| mouse_clicks | Количество кликов мышью |
| mouse_distance_px | Пройденное расстояние мыши (пиксели) |
| scroll_count | Количество прокруток |
| active_window | Заголовок активного окна |
| active_app | Имя активного приложения |
| is_idle | Был ли пользователь неактивен |
| cpu_percent | Загрузка CPU |
| ram_used_percent | Использование RAM |
| disk_used_percent | Использование диска |

## Подключение пользователей (RDP)

### Windows
1. Win+R → `mstsc`
2. Ввести IP сервера
3. Логин/пароль

### Mac
1. Установить Microsoft Remote Desktop из App Store
2. Add PC → ввести IP
3. Connect

### Linux
```bash
xfreerdp /v:SERVER_IP /u:username
# или
remmina
```

## Структура проекта

```
activity-tracker/
├── server/
│   ├── docker-compose.yml
│   └── api/
│       ├── main.py
│       ├── models.py
│       ├── schemas.py
│       └── routers/
│           ├── ingest.py
│           ├── machines.py
│           └── activity.py
├── agent/
│   ├── requirements.txt
│   ├── install.sh
│   └── tracker/
│       ├── main.py
│       ├── config.py
│       ├── buffer.py
│       ├── sender.py
│       ├── system_stats.py
│       └── backends/
│           └── linux.py
└── deploy/
    ├── single-user-vps.sh
    └── multi-user-vps.sh
```
