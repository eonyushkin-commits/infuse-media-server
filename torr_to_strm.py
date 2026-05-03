import os
import requests
import re
import urllib.parse
import time
import sys
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ================= НАСТРОЙКИ (берутся из .env или системных) =================
TORR_PORT = os.getenv("TORR_PORT", "8090")
TORR_INTERNAL_PORT = os.getenv("TORR_INTERNAL_PORT", "8090")
TORRSERVER_INTERNAL = f"http://torrserver:{TORR_INTERNAL_PORT}"
HOST_IP = os.getenv("HOST_IP", "127.0.0.1")

AUTH_USER = urllib.parse.quote(os.getenv("WEBDAV_USER", "admin"))
AUTH_PASS = urllib.parse.quote(os.getenv("WEBDAV_PASSWORD", ""))
AUTH_PREFIX = f"{AUTH_USER}:{AUTH_PASS}@" if AUTH_PASS else ""

TORRSERVER_PUBLIC = f"http://{AUTH_PREFIX}{HOST_IP}:{TORR_PORT}"
OUTPUT_DIR = "/app/strm_library"
VIDEO_EXTENSIONS = ('.mkv', '.mp4', '.avi', '.ts', '.m2ts', '.m4v')
WAKEUP_DELAY = 10
MAX_RETRIES = 3
INTERVAL = 300
# ==============================================================================

session = requests.Session()

retry_config = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=(500, 502, 503, 504),
    allowed_methods=("HEAD", "GET", "POST")
)
adapter = HTTPAdapter(max_retries=retry_config)
session.mount("http://", adapter)
session.mount("https://", adapter)


def log(level: str, message: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    print(f"{ts} [UTC] [{level}] {message}", flush=True)


def clean_title(filename):
    name = os.path.splitext(filename)[0]
    name = name.replace('.', ' ').replace('_', ' ')

    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', name)
    season_match = re.search(r'\bS\d{2}E\d{2}\b', name, re.IGNORECASE)

    if season_match:
        clean_name = name[:season_match.end()].strip()
    elif year_match:
        clean_name = name[:year_match.end()].strip()
    else:
        trash_words = [r'1080p', r'720p', r'2160p', r'4K', r'WEB-DL',
                       r'BDRip', r'HDR', r'DUB', r'HEVC', r'H\.264']
        pattern = re.compile(r'\b(' + '|'.join(trash_words) + r')\b', re.IGNORECASE)
        match = pattern.search(name)
        clean_name = name[:match.start()].strip() if match else name.strip()

    clean_name = re.sub(r'\s+', ' ', clean_name).strip()
    return clean_name or "unknown_title"


def get_torrents():
    try:
        response = session.post(
            f"{TORRSERVER_INTERNAL}/torrents",
            json={"action": "list"},
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log("ERROR", f"⚠️ Ошибка получения списка торрентов: {e}")
        return None


def main():
    if not HOST_IP or HOST_IP == "127.0.0.1":
        log(
            "WARN",
            "⚠️ HOST_IP не задан или указан localhost — Infuse не сможет воспроизвести видео!"
        )

    try:
        int(TORR_PORT)
    except ValueError:
        log(
            "ERROR",
            f"⚠️ TORR_PORT имеет некорректное значение: {TORR_PORT} — ссылки в .strm будут битые"
        )
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    torrents = get_torrents()
    if torrents is None:
        return

    active_hashes_set = set()
    for t in torrents:
        t_hash = t.get("hash")
        if t_hash:
            active_hashes_set.add(t_hash)
        else:
            t_title = t.get("title", "Неизвестное_название")
            log(
                "WARN",
                f"⚠️ Пропущен торрент без хэша (ожидает инициализации или ошибка). "
                f"Название: {t_title}"
            )

    if not active_hashes_set:
        return

    pending_hashes = list(active_hashes_set)
    ready_files = {}

    for attempt in range(MAX_RETRIES):
        still_pending = []

        for t_hash in pending_hashes:
            try:
                t_resp = session.post(
                    f"{TORRSERVER_INTERNAL}/torrents",
                    json={"action": "get", "hash": t_hash},
                    timeout=10
                )
                t_resp.raise_for_status()

                t_data = t_resp.json()
                files = t_data.get("file_stats", [])

                if files:
                    ready_files[t_hash] = files
                    log("INFO", f"✅ {t_hash[:8]}...: получено {len(files)} файлов")
                else:
                    log(
                        "INFO",
                        f"⏳ {t_hash[:8]}...: file_stats пуст, торрент ещё загружается"
                    )
                    still_pending.append(t_hash)
            except Exception as e:
                log("ERROR", f"⚠️ {t_hash[:8]}...: ошибка запроса — {e}")
                still_pending.append(t_hash)

        pending_hashes = still_pending

        if not pending_hashes:
            break

        if attempt < MAX_RETRIES - 1:
            log(
                "INFO",
                f"Ожидают: {len(pending_hashes)} торрентов. "
                f"Пауза {WAKEUP_DELAY} сек (попытка {attempt + 1}/{MAX_RETRIES} завершена)..."
            )
            time.sleep(WAKEUP_DELAY)

    if pending_hashes:
        log(
            "WARN",
            f"⚠️ Пропущено {len(pending_hashes)} торрентов после {MAX_RETRIES} попыток: "
            f"метаданные недоступны. Хэши: {[h[:8] for h in pending_hashes]}"
        )

    for t_hash, files in ready_files.items():
        for idx, file_info in enumerate(files):
            file_path = file_info.get("path", "")
            if not file_path.lower().endswith(VIDEO_EXTENSIONS):
                continue

            filename = os.path.basename(file_path)
            encoded_filename = urllib.parse.quote(filename)

            file_id = file_info.get("id", idx + 1)
            stream_url = (
                f"{TORRSERVER_PUBLIC}/stream/{encoded_filename}"
                f"?link={t_hash}&index={file_id}&play"
            )

            strm_filepath = os.path.join(
                OUTPUT_DIR,
                f"{clean_title(filename)}.{t_hash[:8]}.strm"
            )

            try:
                if os.path.exists(strm_filepath):
                    with open(strm_filepath, 'r', encoding='utf-8') as f:
                        if f.read() == stream_url:
                            continue
                    action_msg = "🔄 Обновлён"
                else:
                    action_msg = "🎬 Создан"

                tmp_filepath = f"{strm_filepath}.tmp"
                with open(tmp_filepath, 'w', encoding='utf-8') as f:
                    f.write(stream_url)

                os.replace(tmp_filepath, strm_filepath)
                log("INFO", f"{action_msg}: {strm_filepath}")

            except Exception as e:
                try:
                    if 'tmp_filepath' in locals() and os.path.exists(tmp_filepath):
                        os.remove(tmp_filepath)
                except Exception:
                    pass
                log("ERROR", f"⚠️ Ошибка записи файла {strm_filepath}: {e}")

    for file in os.listdir(OUTPUT_DIR):
        if file.endswith('.strm'):
            filepath = os.path.join(OUTPUT_DIR, file)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()

                match = re.search(r'link=([a-fA-F0-9]{40})', content)
                if match and match.group(1) not in active_hashes_set:
                    os.remove(filepath)
                    log("INFO", f"🗑 Удалён устаревший файл: {file}")
            except Exception as e:
                log("ERROR", f"⚠️ Ошибка при чтении/удалении файла {filepath}: {e}")


if __name__ == "__main__":
    log(
        "INFO",
        f"🚀 Парсер запущен. Internal: {TORRSERVER_INTERNAL} | "
        f"Public: {TORRSERVER_PUBLIC} | Интервал: {INTERVAL // 60} мин."
    )

    while True:
        try:
            main()
        except Exception as e:
            log("ERROR", f"⚠️ Критическая ошибка в главном цикле: {e}")
        time.sleep(INTERVAL)
