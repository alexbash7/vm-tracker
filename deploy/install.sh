#!/usr/bin/env bash
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}  Activity Tracker - VPS Setup${NC}"
echo -e "${GREEN}======================================${NC}"

# --- LOAD CONFIG ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/config.env" ]; then
    export $(grep -v '^#' "$SCRIPT_DIR/config.env" | xargs)
else
    echo -e "${RED}config.env not found! Exiting...${NC}"
    exit 1
fi

# --- CHECK ROOT ---
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root (sudo ./install.sh)${NC}"
    exit 1
fi

# --- GET MACHINE UUID ---
MACHINE_UUID=$(cat /etc/machine-id 2>/dev/null | head -c 8 || uuidgen | tr -d '-' | head -c 8)
echo -e "Machine UUID: ${CYAN}${MACHINE_UUID}${NC}"
echo -e "Users to create: ${CYAN}${USER_COUNT}${NC}"
echo -e "Tracker API: ${CYAN}${TRACKER_API_URL}${NC}"
echo ""

# --- SYSTEM UPDATE ---
echo -e "${GREEN}[1/6] Updating system...${NC}"
apt update && apt upgrade -y

# --- INSTALL PACKAGES ---
echo -e "${GREEN}[2/6] Installing packages...${NC}"
apt install -y \
    curl \
    wget \
    git \
    unzip \
    nano \
    htop \
    ca-certificates \
    gnupg \
    locales \
    xfce4 \
    xfce4-goodies \
    xfce4-terminal \
    dbus-x11 \
    xrdp \
    python3 \
    python3-pip \
    python3-venv

# --- FIX LOCALE ---
echo -e "${GREEN}[3/6] Configuring locale...${NC}"
locale-gen en_US.UTF-8
update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# --- INSTALL BROWSERS ---
echo -e "${GREEN}[4/6] Installing browsers...${NC}"

# Google Chrome
if ! command -v google-chrome &> /dev/null; then
    wget -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    apt install -y /tmp/chrome.deb
    rm /tmp/chrome.deb
fi

# Firefox
apt install -y firefox

# --- SETUP TRACKER ---
echo -e "${GREEN}[5/6] Setting up Activity Tracker...${NC}"

TRACKER_DIR="/opt/activity-tracker"
mkdir -p "$TRACKER_DIR"

# Copy tracker files
cp -r "$SCRIPT_DIR/../agent/tracker/"* "$TRACKER_DIR/"
cp "$SCRIPT_DIR/../agent/requirements.txt" "$TRACKER_DIR/"

# Create virtual environment
python3 -m venv "$TRACKER_DIR/venv"
"$TRACKER_DIR/venv/bin/pip" install --quiet --upgrade pip
"$TRACKER_DIR/venv/bin/pip" install --quiet -r "$TRACKER_DIR/requirements.txt"

# --- CREATE USERS ---
echo -e "${GREEN}[6/6] Creating users...${NC}"

CREDENTIALS_FILE="/root/users-credentials.txt"
echo "# Activity Tracker - User Credentials" > "$CREDENTIALS_FILE"
echo "# Generated: $(date)" >> "$CREDENTIALS_FILE"
echo "# Machine UUID: $MACHINE_UUID" >> "$CREDENTIALS_FILE"
echo "" >> "$CREDENTIALS_FILE"

echo ""
echo -e "${CYAN}========== USER CREDENTIALS ==========${NC}"

for i in $(seq 1 $USER_COUNT); do
    USERNAME="user${i}"
    PASSWORD=$(openssl rand -base64 12 | tr -dc 'a-zA-Z0-9' | head -c 12)
    MACHINE_ID="vm-${MACHINE_UUID}-${USERNAME}"
    
    # Create user if not exists
    if ! id "$USERNAME" &>/dev/null; then
        useradd -m -s /bin/bash "$USERNAME"
    fi
    echo "$USERNAME:$PASSWORD" | chpasswd
    
    # Setup XFCE session for xrdp
    echo "xfce4-session" > "/home/$USERNAME/.xsession"
    chown "$USERNAME:$USERNAME" "/home/$USERNAME/.xsession"
    
    # Create tracker config directory
    USER_CONFIG_DIR="/home/$USERNAME/.config/activity-tracker"
    USER_DATA_DIR="/home/$USERNAME/.local/share/activity-tracker"
    mkdir -p "$USER_CONFIG_DIR"
    mkdir -p "$USER_DATA_DIR"
    
    # Create tracker config
    cat > "$USER_CONFIG_DIR/config.yaml" <<EOF
server_url: "${TRACKER_API_URL}"
machine_id: "${MACHINE_ID}"
user_label: "${MACHINE_ID}"
collect_interval_sec: ${TRACKER_COLLECT_INTERVAL:-60}
send_interval_sec: ${TRACKER_SEND_INTERVAL:-300}
buffer_path: "${USER_DATA_DIR}/buffer.db"
features:
  screenshots: false
  track_system_stats: true
EOF
    
    # Create autostart for tracker
    mkdir -p "/home/$USERNAME/.config/autostart"
    cat > "/home/$USERNAME/.config/autostart/activity-tracker.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Activity Tracker
Exec=${TRACKER_DIR}/venv/bin/python ${TRACKER_DIR}/main.py ${USER_CONFIG_DIR}/config.yaml
Hidden=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF
    
    # Set ownership
    chown -R "$USERNAME:$USERNAME" "/home/$USERNAME/.config"
    chown -R "$USERNAME:$USERNAME" "/home/$USERNAME/.local"
    
    # Save credentials
    echo "$USERNAME / $PASSWORD / $MACHINE_ID" >> "$CREDENTIALS_FILE"
    
    echo -e "${YELLOW}$USERNAME${NC} / $PASSWORD → machine_id: ${CYAN}$MACHINE_ID${NC}"
done

chmod 600 "$CREDENTIALS_FILE"

echo -e "${CYAN}======================================${NC}"

# --- CONFIGURE XRDP ---
echo -e "${GREEN}Configuring xrdp...${NC}"
systemctl enable xrdp
systemctl restart xrdp

# --- GET SERVER IP ---
SERVER_IP=$(hostname -I | awk '{print $1}')

# --- DONE ---
echo ""
echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}  Installation Complete!${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""
echo -e "Server IP: ${CYAN}${SERVER_IP}${NC}"
echo -e "RDP Port: ${CYAN}3389${NC}"
echo ""
echo -e "Credentials saved to: ${YELLOW}/root/users-credentials.txt${NC}"
echo ""
echo -e "${YELLOW}How to connect:${NC}"
echo -e "  Windows: Win+R → mstsc → Enter IP: ${SERVER_IP}"
echo -e "  Mac: Microsoft Remote Desktop → Add PC → ${SERVER_IP}"
echo ""
echo -e "${YELLOW}To change password:${NC}"
echo -e "  sudo ./change-password.sh user1 newpassword123"
echo ""
echo -e "${GREEN}Reboot recommended: sudo reboot${NC}"
