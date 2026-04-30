import os
import requests
import re
import urllib.parse
import time
import sys


# ================= НАСТРОЙКИ (берутся из .env или системных) =================
TORR_PORT = os.getenv("TORR_PORT", "8090")
TORRSERVER_INTERNAL = f"http://torrserver:{TORR_PORT}"
HOST_IP = os.getenv("HOST_IP", "127.0.0.1")
TORRSERVER_PUBLIC = f"http://{HOST_IP}:{TORR_PORT}"
OUTPUT_DIR = "/app/strm_library"
VIDEO_EXTENSIONS = ('.mkv', '.mp4', '.avi', '.ts', '.m2ts', '.m4v')
WAKEUP_DELAY = 10
MAX_RETRIES = 3
INTERVAL = 300
# ==============================================================================


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
        response = requests.post(
            f"{TORRSERVER_INTERNAL}/torrents",
            json={"action": "list"},
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"⚠️ Ошибка получения списка торрентов: {e}")
        return None


def main():
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
            print(f"⚠️ Пропущен торрент без хэша (ожидает инициализации или ошибка). Название: {t_title}")

    if not active_hashes_set:
        return

    pending_hashes = list(active_hashes_set)
    ready_files = {}

    for attempt in range(MAX_RETRIES):
        still_pending = []

        for t_hash in pending_hashes:
            try:
                t_resp = requests.post(
                    f"{TORRSERVER_INTERNAL}/torrents",
                    json={"action": "get", "hash": t_hash},
                    timeout=10
                )
                t_resp.raise_for_status()

                t_data = t_resp.json()
                files = t_data.get("file_stats", [])

                if files:
                    ready_files[t_hash] = files
                    print(f"✅ {t_hash[:8]}...: получено {len(files)} файлов")
                else:
                    print(f"⏳ {t_hash[:8]}...: file_stats пуст, торрент ещё загружается")
                    still_pending.append(t_hash)
            except Exception as e:
                print(f"⚠️ {t_hash[:8]}...: ошибка запроса — {e}")
                still_pending.append(t_hash)

        pending_hashes = still_pending

        if not pending_hashes:
            break

        if attempt < MAX_RETRIES - 1:
            print(
                f"Ожидают: {len(pending_hashes)} торрентов. "
                f"Пауза {WAKEUP_DELAY} сек (попытка {attempt + 1}/{MAX_RETRIES} завершена)..."
            )
            time.sleep(WAKEUP_DELAY)

    if pending_hashes:
        print(
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

            strm_filepath = os.path.join(OUTPUT_DIR, f"{clean_title(filename)}.strm")

            try:
                with open(strm_filepath, 'x', encoding='utf-8') as f:
                    f.write(stream_url)
                print(f"🎬 Создан: {strm_filepath}")
            except FileExistsError:
                with open(strm_filepath, 'r', encoding='utf-8') as f:
                    existing_url = f.read()
                if existing_url != stream_url:
                    with open(strm_filepath, 'w', encoding='utf-8') as f:
                        f.write(stream_url)
                    print(f"🔄 Обновлён: {strm_filepath}")
            except Exception as e:
                print(f"⚠️ Ошибка записи файла {strm_filepath}: {e}")

    for file in os.listdir(OUTPUT_DIR):
        if file.endswith('.strm'):
            filepath = os.path.join(OUTPUT_DIR, file)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()

                match = re.search(r'link=([a-fA-F0-9]{40})', content)
                if match and match.group(1) not in active_hashes_set:
                    os.remove(filepath)
                    print(f"🗑 Удален: {file}")
            except Exception as e:
                print(f"⚠️ Ошибка при чтении/удалении файла {filepath}: {e}")

    sys.stdout.flush()


if __name__ == "__main__":
    print(f"🚀 Парсер запущен. Internal: {TORRSERVER_INTERNAL} | Public: {TORRSERVER_PUBLIC} | Интервал: {INTERVAL // 60} мин.")
    sys.stdout.flush()

    while True:
        try:
            main()
        except Exception as e:
            print(f"⚠️ Критическая ошибка в главном цикле: {e}")
            sys.stdout.flush()

        time.sleep(INTERVAL)