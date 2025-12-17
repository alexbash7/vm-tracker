#!/bin/bash
# Multi-User VPS Setup with Activity Tracker
# Разворачивает VPS с xrdp и несколькими пользователями

set -e

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Параметры
USERS_COUNT="${1:-3}"
TRACKER_API="${2:-http://localhost:8000}"
AGENT_REPO="${3:-https://github.com/YOUR_REPO/activity-tracker}"

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}  Multi-User VPS Setup${NC}"
echo -e "${GREEN}======================================${NC}"
echo -e "Users count: ${YELLOW}${USERS_COUNT}${NC}"
echo -e "Tracker API: ${YELLOW}${TRACKER_API}${NC}"

# Проверка root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root${NC}"
    exit 1
fi

# Уникальный ID машины
MACHINE_UUID=$(cat /etc/machine-id 2>/dev/null | head -c 8 || uuidgen | tr -d '-' | head -c 8)
VM_NAME="vm-${MACHINE_UUID}"

echo -e "\nVM Name: ${CYAN}${VM_NAME}${NC}"

# Обновление системы
echo -e "\n${GREEN}[1/5] Updating system...${NC}"
apt-get update -qq
apt-get upgrade -y -qq

# Установка xrdp и desktop
echo -e "\n${GREEN}[2/5] Installing xrdp and desktop environment...${NC}"
apt-get install -y -qq \
    xrdp \
    xfce4 \
    xfce4-goodies \
    xfce4-terminal \
    dbus-x11 \
    x11-xserver-utils

# Установка базового софта
echo -e "\n${GREEN}[3/5] Installing software...${NC}"
apt-get install -y -qq \
    chromium-browser \
    firefox \
    libreoffice \
    file-roller \
    gedit \
    xdotool \
    xprintidle \
    python3 \
    python3-pip \
    python3-venv

# Настройка xrdp
echo -e "\n${GREEN}[4/5] Configuring xrdp...${NC}"
sed -i 's/^port=3389/port=3389/' /etc/xrdp/xrdp.ini

# Создание пользователей
echo -e "\n${GREEN}[5/5] Creating users...${NC}"
echo ""
echo -e "${CYAN}========== USER CREDENTIALS ==========${NC}"

# Установка агента в общую директорию
AGENT_DIR="/opt/activity-tracker"
mkdir -p "$AGENT_DIR"

# Скачиваем/копируем файлы агента (здесь предполагаем что они уже есть локально)
# В реальности можно скачать из git или скопировать
if [ -d "./agent/tracker" ]; then
    cp -r ./agent/tracker/* "$AGENT_DIR/"
    cp ./agent/requirements.txt "$AGENT_DIR/"
fi

# Создаём venv один раз
python3 -m venv "$AGENT_DIR/venv"
"$AGENT_DIR/venv/bin/pip" install --quiet --upgrade pip
if [ -f "$AGENT_DIR/requirements.txt" ]; then
    "$AGENT_DIR/venv/bin/pip" install --quiet -r "$AGENT_DIR/requirements.txt"
fi

# Создание пользователей
for i in $(seq 1 $USERS_COUNT); do
    USERNAME="user${i}"
    PASSWORD=$(openssl rand -base64 12 | tr -dc 'a-zA-Z0-9' | head -c 12)
    
    # Создать пользователя если не существует
    if ! id "$USERNAME" &>/dev/null; then
        useradd -m -s /bin/bash "$USERNAME"
    fi
    echo "$USERNAME:$PASSWORD" | chpasswd
    
    # Настроить xfce
    echo "xfce4-session" > "/home/$USERNAME/.xsession"
    chown "$USERNAME:$USERNAME" "/home/$USERNAME/.xsession"
    
    # Конфиг трекера для пользователя
    USER_CONFIG_DIR="/home/$USERNAME/.config/activity-tracker"
    USER_DATA_DIR="/home/$USERNAME/.local/share/activity-tracker"
    mkdir -p "$USER_CONFIG_DIR"
    mkdir -p "$USER_DATA_DIR"
    
    MACHINE_ID="${VM_NAME}-${USERNAME}"
    
    cat > "$USER_CONFIG_DIR/config.yaml" <<EOF
server_url: "${TRACKER_API}"
machine_id: "${MACHINE_ID}"
user_label: "${MACHINE_ID}"
collect_interval_sec: 60
send_interval_sec: 300
buffer_path: "${USER_DATA_DIR}/buffer.db"
features:
  screenshots: false
  track_system_stats: true
EOF
    
    # Автозапуск трекера при входе в сессию
    mkdir -p "/home/$USERNAME/.config/autostart"
    cat > "/home/$USERNAME/.config/autostart/activity-tracker.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Activity Tracker
Exec=${AGENT_DIR}/venv/bin/python ${AGENT_DIR}/main.py ${USER_CONFIG_DIR}/config.yaml
Hidden=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF
    
    # Права доступа
    chown -R "$USERNAME:$USERNAME" "/home/$USERNAME/.config"
    chown -R "$USERNAME:$USERNAME" "/home/$USERNAME/.local"
    
    echo -e "${YELLOW}User ${i}:${NC} $USERNAME / $PASSWORD  →  Machine ID: ${MACHINE_ID}"
done

echo -e "${CYAN}======================================${NC}"

# Запуск xrdp
systemctl enable xrdp
systemctl restart xrdp

# Информация о подключении
SERVER_IP=$(hostname -I | awk '{print $1}')

echo ""
echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}  Setup Complete!${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""
echo -e "Connect via RDP to: ${CYAN}${SERVER_IP}:3389${NC}"
echo ""
echo -e "${YELLOW}Windows:${NC} mstsc.exe → Enter: ${SERVER_IP}"
echo -e "${YELLOW}Mac:${NC} Microsoft Remote Desktop → Add PC: ${SERVER_IP}"
echo -e "${YELLOW}Linux:${NC} remmina or xfreerdp"
echo ""
echo -e "Tracker API: ${TRACKER_API}"
echo ""
