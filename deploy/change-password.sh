#!/usr/bin/env bash

# Change password for a user
# Usage: sudo ./change-password.sh username newpassword

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: sudo ./change-password.sh <username> <new_password>"
    echo "Example: sudo ./change-password.sh user1 MyNewPass123"
    exit 1
fi

USERNAME=$1
NEW_PASSWORD=$2

# Check if user exists
if ! id "$USERNAME" &>/dev/null; then
    echo "Error: User '$USERNAME' does not exist"
    exit 1
fi

# Change password
echo "$USERNAME:$NEW_PASSWORD" | chpasswd

if [ $? -eq 0 ]; then
    echo "Password changed successfully for user: $USERNAME"
    
    # Update credentials file
    CREDENTIALS_FILE="/root/users-credentials.txt"
    if [ -f "$CREDENTIALS_FILE" ]; then
        # Get machine_id for this user
        MACHINE_ID=$(grep "^$USERNAME /" "$CREDENTIALS_FILE" | awk -F' / ' '{print $3}')
        
        # Update line in credentials file
        sed -i "s|^$USERNAME / .* / $MACHINE_ID|$USERNAME / $NEW_PASSWORD / $MACHINE_ID|" "$CREDENTIALS_FILE"
        echo "Credentials file updated"
    fi
else
    echo "Error: Failed to change password"
    exit 1
fi
