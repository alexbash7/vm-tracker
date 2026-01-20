#!/opt/homebrew/bin/python3
import json
import struct
import sys
import os

# Читаем входящее сообщение от Chrome (обязательно!)
raw_length = sys.stdin.buffer.read(4)
if len(raw_length) == 0:
    sys.exit(0)
message_length = struct.unpack('I', raw_length)[0]
message = sys.stdin.buffer.read(message_length).decode('utf-8')

# Читаем userEmail из файла
config_path = os.path.expanduser("~/.tracker-user.conf")
try:
    with open(config_path, 'r') as f:
        user_email = f.read().strip()
except:
    user_email = None

# Формируем ответ
response = json.dumps({
    "userEmail": user_email,
    "authToken": "manual-tracker-key-2026"
})

# Отправляем в формате Chrome Native Messaging
sys.stdout.buffer.write(struct.pack('I', len(response)))
sys.stdout.buffer.write(response.encode())
sys.stdout.buffer.flush()
