def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    torrents = get_torrents()
    if torrents is None:
        return

    # === Изменения по замечанию №3 ===
    active_hashes_set = set()
    for t in torrents:
        t_hash = t.get("hash")
        if t_hash:
            active_hashes_set.add(t_hash)
        else:
            t_title = t.get("title", "Неизвестное_название")
            print(f"⚠️ Пропущен торрент без хэша (ожидает инициализации или ошибка). Название: {t_title}")
    # =================================

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

        # Ключевой фикс: обновляем pending_hashes до break
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