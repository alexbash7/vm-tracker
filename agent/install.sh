#!/bin/bash
# Activity Tracker Agent - Installation Script

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== Activity Tracker Agent Installation ===${NC}"

# Параметры
SERVER_URL="${1:-http://localhost:8000}"
INSTALL_DIR="/opt/activity-tracker"
CONFIG_DIR="/etc/activity-tracker"
DATA_DIR="/var/lib/activity-tracker"
USER_NAME="${SUDO_USER:-$USER}"

# Проверка root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root (sudo)${NC}"
    exit 1
fi

# Генерация уникального machine_id
MACHINE_UUID=$(cat /etc/machine-id 2>/dev/null | head -c 8 || uuidgen | tr -d '-' | head -c 8)
MACHINE_ID="vm-${MACHINE_UUID}-${USER_NAME}"

echo -e "${YELLOW}Machine ID: ${MACHINE_ID}${NC}"
echo -e "${YELLOW}Server URL: ${SERVER_URL}${NC}"

# Установка зависимостей
echo -e "\n${GREEN}Installing dependencies...${NC}"
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv xdotool xprintidle

# Создание директорий
echo -e "\n${GREEN}Creating directories...${NC}"
mkdir -p "$INSTALL_DIR"
mkdir -p "$CONFIG_DIR"
mkdir -p "$DATA_DIR"

# Копирование файлов агента
echo -e "\n${GREEN}Installing agent...${NC}"
cp -r tracker/* "$INSTALL_DIR/"
cp requirements.txt "$INSTALL_DIR/"

# Создание виртуального окружения
echo -e "\n${GREEN}Setting up Python environment...${NC}"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# Создание конфига
echo -e "\n${GREEN}Creating configuration...${NC}"
cat > "$CONFIG_DIR/config.yaml" <<EOF
server_url: "${SERVER_URL}"
machine_id: "${MACHINE_ID}"
user_label: "${MACHINE_ID}"
collect_interval_sec: 60
send_interval_sec: 300
buffer_path: "${DATA_DIR}/buffer.db"
features:
  screenshots: false
  track_system_stats: true
EOF

# Создание systemd сервиса
echo -e "\n${GREEN}Creating systemd service...${NC}"
cat > /etc/systemd/system/activity-tracker.service <<EOF
[Unit]
Description=Activity Tracker Agent
After=network.target graphical-session.target
Wants=graphical-session.target

[Service]
Type=simple
User=${USER_NAME}
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/${USER_NAME}/.Xauthority
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/main.py ${CONFIG_DIR}/config.yaml
Restart=always
RestartSec=10

[Install]
WantedBy=graphical-session.target
EOF

# Для автозапуска при логине (xfce/desktop)
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
chown "${USER_NAME}:${USER_NAME}" "/home/${USER_NAME}/.config/autostart/activity-tracker.desktop"

# Права доступа
chown -R "${USER_NAME}:${USER_NAME}" "$DATA_DIR"

# Включение и запуск сервиса
echo -e "\n${GREEN}Enabling and starting service...${NC}"
systemctl daemon-reload
systemctl enable activity-tracker
systemctl start activity-tracker || true

echo -e "\n${GREEN}=== Installation Complete ===${NC}"
echo -e "Machine ID: ${YELLOW}${MACHINE_ID}${NC}"
echo -e "Config: ${CONFIG_DIR}/config.yaml"
echo -e "Logs: journalctl -u activity-tracker -f"
echo -e "\nService status:"
systemctl status activity-tracker --no-pager || true
