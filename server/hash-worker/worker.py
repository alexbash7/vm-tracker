"""
Screenshot Hash Worker

Скачивает скриншоты с Wasabi S3, вычисляет perceptual hash (pHash),
и сохраняет в базу для фильтрации дубликатов.

pHash игнорирует мелкие изменения (часы, курсор, колёсико загрузки),
поэтому похожие скриншоты получат одинаковый/близкий хеш.
"""

import os
import time
import hashlib
import logging
from io import BytesIO
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import RealDictCursor
import boto3
from botocore.exceptions import ClientError
from PIL import Image
import imagehash

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Конфигурация из env
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://tracker:tracker_pass@localhost:5432/activity_tracker")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "https://s3.wasabisys.com")
S3_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
S3_BUCKET = os.getenv("S3_BUCKET", "instaloader")

# Настройки воркера
BATCH_SIZE = int(os.getenv("HASH_BATCH_SIZE", "50"))
SLEEP_INTERVAL = int(os.getenv("HASH_SLEEP_INTERVAL", "30"))
PHASH_SIZE = int(os.getenv("PHASH_SIZE", "16"))  # 16x16 = 256 бит, более точный


def get_db_connection():
    """Создать подключение к PostgreSQL"""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def get_s3_client():
    """Создать S3 клиент для Wasabi"""
    return boto3.client(
        's3',
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY
    )


def parse_s3_url(url: str) -> tuple[str, str]:
    """
    Извлечь bucket и key из S3 URL.
    Формат: https://s3.wasabisys.com/bucket/path/to/file.jpg
    """
    parsed = urlparse(url)
    path_parts = parsed.path.lstrip('/').split('/', 1)
    
    if len(path_parts) == 2:
        bucket, key = path_parts
    else:
        # Fallback: использовать bucket из env
        bucket = S3_BUCKET
        key = parsed.path.lstrip('/')
    
    return bucket, key


def download_image(s3_client, url: str) -> bytes | None:
    """Скачать изображение с S3"""
    try:
        bucket, key = parse_s3_url(url)
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return response['Body'].read()
    except ClientError as e:
        logger.error(f"S3 download error for {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error downloading {url}: {e}")
        return None


def compute_hashes(image_data: bytes) -> tuple[str, int] | None:
    """
    Вычислить MD5 и pHash для изображения.
    
    Returns:
        (content_hash, phash_int) или None при ошибке
    """
    try:
        # MD5 - точный хеш
        content_hash = hashlib.md5(image_data).hexdigest()
        
        # pHash - перцептуальный хеш
        image = Image.open(BytesIO(image_data))
        
        # Конвертируем в RGB если нужно (для PNG с альфа-каналом)
        if image.mode in ('RGBA', 'P'):
            image = image.convert('RGB')
        
        # pHash с увеличенным размером для большей точности
        phash = imagehash.phash(image, hash_size=PHASH_SIZE)
        
        # Конвертируем в int для хранения в BIGINT
        # Для hash_size=16 это 256 бит, не влезет в BIGINT (64 бит)
        # Поэтому берём только первые 64 бита или используем hash_size=8
        phash_int = int(str(phash), 16)
        
        return content_hash, phash_int
        
    except Exception as e:
        logger.error(f"Error computing hashes: {e}")
        return None


def ensure_columns_exist(conn):
    """Добавить колонки если их нет"""
    with conn.cursor() as cur:
        # Проверяем существование колонок
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'screenshots' 
            AND column_name IN ('content_hash', 'phash', 'hash_processed_at')
        """)
        existing = {row['column_name'] for row in cur.fetchall()}
        
        if 'content_hash' not in existing:
            logger.info("Adding column: content_hash")
            cur.execute("ALTER TABLE screenshots ADD COLUMN content_hash VARCHAR(64)")
        
        if 'phash' not in existing:
            logger.info("Adding column: phash")
            cur.execute("ALTER TABLE screenshots ADD COLUMN phash NUMERIC")
        
        if 'hash_processed_at' not in existing:
            logger.info("Adding column: hash_processed_at")
            cur.execute("ALTER TABLE screenshots ADD COLUMN hash_processed_at TIMESTAMP WITH TIME ZONE")
        
        # Индекс для быстрого поиска по phash
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_screenshots_phash 
            ON screenshots(phash) 
            WHERE phash IS NOT NULL
        """)
        
        conn.commit()
        logger.info("Database schema ready")


def get_unprocessed_screenshots(conn, limit: int) -> list[dict]:
    """Получить скриншоты без хеша"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, image_path 
            FROM screenshots 
            WHERE phash IS NULL 
            AND image_path IS NOT NULL
            ORDER BY id DESC 
            LIMIT %s
        """, (limit,))
        return cur.fetchall()


def update_screenshot_hashes(conn, screenshot_id: int, content_hash: str, phash_int: int):
    """Обновить хеши для скриншота"""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE screenshots 
            SET content_hash = %s, 
                phash = %s, 
                hash_processed_at = NOW()
            WHERE id = %s
        """, (content_hash, phash_int, screenshot_id))
    conn.commit()


def mark_as_failed(conn, screenshot_id: int):
    """Пометить скриншот как обработанный с ошибкой (phash = -1)"""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE screenshots 
            SET phash = -1, 
                hash_processed_at = NOW()
            WHERE id = %s
        """, (screenshot_id,))
    conn.commit()


def process_batch(conn, s3_client) -> int:
    """
    Обработать пачку скриншотов.
    
    Returns:
        Количество обработанных скриншотов
    """
    screenshots = get_unprocessed_screenshots(conn, BATCH_SIZE)
    
    if not screenshots:
        return 0
    
    processed = 0
    
    for screenshot in screenshots:
        screenshot_id = screenshot['id']
        image_url = screenshot['image_path']
        
        # Скачиваем
        image_data = download_image(s3_client, image_url)
        
        if image_data is None:
            mark_as_failed(conn, screenshot_id)
            continue
        
        # Вычисляем хеши
        result = compute_hashes(image_data)
        
        if result is None:
            mark_as_failed(conn, screenshot_id)
            continue
        
        content_hash, phash_int = result
        
        # Сохраняем
        update_screenshot_hashes(conn, screenshot_id, content_hash, phash_int)
        processed += 1
    
    return processed


def get_stats(conn) -> dict:
    """Получить статистику обработки"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(phash) as processed,
                COUNT(*) FILTER (WHERE phash = -1) as failed,
                COUNT(*) FILTER (WHERE phash IS NULL) as pending
            FROM screenshots
        """)
        return cur.fetchone()


def main():
    """Основной цикл воркера"""
    logger.info("=" * 50)
    logger.info("Screenshot Hash Worker starting...")
    logger.info(f"Database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'localhost'}")
    logger.info(f"S3 Endpoint: {S3_ENDPOINT}")
    logger.info(f"Batch size: {BATCH_SIZE}")
    logger.info(f"Sleep interval: {SLEEP_INTERVAL}s")
    logger.info(f"pHash size: {PHASH_SIZE}x{PHASH_SIZE}")
    logger.info("=" * 50)
    
    # Проверяем S3 credentials
    if not S3_ACCESS_KEY or not S3_SECRET_KEY:
        logger.error("S3 credentials not set! Set AWS_ACCESS_KEY and AWS_SECRET_ACCESS_KEY")
        return
    
    # Подключаемся к БД
    conn = get_db_connection()
    s3_client = get_s3_client()
    
    # Добавляем колонки если нужно
    ensure_columns_exist(conn)
    
    # Начальная статистика
    stats = get_stats(conn)
    logger.info(f"Initial stats: {stats['total']} total, {stats['processed']} processed, {stats['pending']} pending")
    
    # Основной цикл
    while True:
        try:
            processed = process_batch(conn, s3_client)
            
            if processed > 0:
                stats = get_stats(conn)
                logger.info(f"Processed {processed} screenshots. Pending: {stats['pending']}")
            else:
                logger.debug("No screenshots to process, sleeping...")
            
            time.sleep(SLEEP_INTERVAL)
            
        except psycopg2.OperationalError as e:
            logger.error(f"Database connection error: {e}")
            logger.info("Reconnecting in 10 seconds...")
            time.sleep(10)
            try:
                conn = get_db_connection()
            except Exception:
                pass
                
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            break
            
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            time.sleep(10)
    
    conn.close()
    logger.info("Worker stopped")


if __name__ == "__main__":
    main()
