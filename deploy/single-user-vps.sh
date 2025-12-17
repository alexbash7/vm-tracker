#!/bin/bash
# Single-User VPS Setup with Activity Tracker
# Добавляет трекер к существующей VPS

set -e

# Цвета
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

TRACKER_API="${1:-http://localhost:8000}"

echo -e "${GREEN}=== Adding Activity Tracker to VPS ===${NC}"
echo -e "Tracker API: ${YELLOW}${TRACKER_API}${NC}"

# Проверка root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

# Текущий пользователь
USER_NAME="${SUDO_USER:-$USER}"

# Уникальный ID
MACHINE_UUID=$(cat /etc/machine-id 2>/dev/null | head -c 8 || uuidgen | tr -d '-' | head -c 8)
MACHINE_ID="vm-${MACHINE_UUID}-${USER_NAME}"

echo -e "Machine ID: ${YELLOW}${MACHINE_ID}${NC}"

# Установка зависимостей
echo -e "\n${GREEN}Installing dependencies...${NC}"
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv xdotool xprintidle

# Директории
INSTALL_DIR="/opt/activity-tracker"
CONFIG_DIR="/home/${USER_NAME}/.config/activity-tracker"
DATA_DIR="/home/${USER_NAME}/.local/share/activity-tracker"

mkdir -p "$INSTALL_DIR"
mkdir -p "$CONFIG_DIR"
mkdir -p "$DATA_DIR"

# Копируем агент (предполагаем что скрипт запускается из директории проекта)
if [ -d "./agent/tracker" ]; then
    cp -r ./agent/tracker/* "$INSTALL_DIR/"
    cp ./agent/requirements.txt "$INSTALL_DIR/"
fi

# Python окружение
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# Конфиг
cat > "$CONFIG_DIR/config.yaml" <<EOF
server_url: "${TRACKER_API}"
machine_id: "${MACHINE_ID}"
user_label: "${MACHINE_ID}"
collect_interval_sec: 60
send_interval_sec: 300
buffer_path: "${DATA_DIR}/buffer.db"
features:
  screenshots: false
  track_system_stats: true
EOF

# Автозапуск
mkdir -p "/home/${USER_NAME}/.config/autostart"
cat > "/home/${USER_NAME}/.config/autostart/activity-tracker.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Activity Tracker
Exec=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/main.py ${CONFIG_DIR}/config.yaml
Hidden=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF

# Права
chown -R "${USER_NAME}:${USER_NAME}" "$CONFIG_DIR"
chown -R "${USER_NAME}:${USER_NAME}" "$DATA_DIR"
chown -R "${USER_NAME}:${USER_NAME}" "/home/${USER_NAME}/.config/autostart"

echo -e "\n${GREEN}=== Done ===${NC}"
echo -e "Machine ID: ${MACHINE_ID}"
echo -e "Config: ${CONFIG_DIR}/config.yaml"
echo -e "Tracker will start on next login"
