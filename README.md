# Infuse Media Server

Контейнеризированный стек для публикации библиотеки TorrServer в **Infuse** через **WebDAV**.

Проект поднимает три сервиса в Docker:

- **TorrServer** — источник торрент-раздач и HTTP-стриминга;
- **Parser** — сервис, который опрашивает TorrServer и генерирует `.strm`-файлы;
- **WebDAV** — публикует каталог `.strm`-файлов для подключения в Infuse.

В результате Infuse видит библиотеку через WebDAV, а при запуске файла использует ссылку из `.strm` для воспроизведения потока через TorrServer.

## Архитектура

Сервисы проекта:

- `torrserver` — контейнер `ghcr.io/yourok/torrserver:latest`, хранит данные в `./ts`, публикуется на внешний порт `TORR_PORT`;
- `parser` — локально собираемый контейнер `strm-parser`, использует код из `./app`, получает `HOST_IP` и `TORR_PORT` через переменные окружения;
- `webdav` — контейнер `ugeek/webdav:amd64`, публикует каталог `./strm-library` в `/media`, использует `WEBDAV_USER` и `WEBDAV_PASSWORD` для авторизации.

Схема работы:

1. Вы добавляете раздачу в TorrServer.
2. Parser обнаруживает её при очередном опросе.
3. Parser создаёт `.strm`-файлы в библиотеке проекта.
4. WebDAV публикует эту библиотеку для Infuse.
5. Infuse индексирует файлы и воспроизводит поток через TorrServer.

## Требования

На сервере должны быть установлены:

- `git`
- `docker`
- `curl`
- Docker Compose v2 или совместимый `docker-compose`

Скрипт установки должен запускаться от `root` или через `sudo`, иначе он завершится с ошибкой.

## Установка

Запустите на сервере:

```bash
curl -O https://raw.githubusercontent.com/eonyushkin-commits/infuse-media-server/refs/heads/main/install.sh
chmod +x install.sh
./install.sh
```

Скрипт:

- клонирует репозиторий в `/opt/infuse-media-server`;
- запрашивает параметры WebDAV и TorrServer;
- создаёт `.env`;
- запускает контейнеры через `docker compose up -d --build`.

## Параметры установки

Во время установки скрипт интерактивно запрашивает:

- `WEBDAV_PORT` — внешний порт WebDAV, по умолчанию `8080`;
- `WEBDAV_USER` — логин WebDAV, по умолчанию `admin`;
- `WEBDAV_PASSWORD` — пароль WebDAV;
- `HOST_IP` — внешний IP-адрес сервера;
- `TORR_PORT` — внешний порт TorrServer, по умолчанию `8090`.

Эти значения сохраняются в файл `.env`, который используется Docker Compose при запуске сервисов.

## Структура каталогов

После установки проект работает из каталога:

```bash
/opt/infuse-media-server
```

Основные рабочие каталоги и файлы:

- `install.sh` — установка, обновление и переконфигурация;
- `.env` — параметры окружения;
- `./app` — код parser-сервиса;
- `./strm-library` — библиотека `.strm`-файлов для Infuse;
- `./ts` — данные TorrServer;
- `docker-compose.yml` — описание контейнеров проекта.

## Обновление

Повторный запуск `install.sh` является штатным способом обновления проекта и изменения параметров:

```bash
cd /opt/infuse-media-server
./install.sh
```

Если репозиторий уже существует, скрипт выполняет `git fetch --all` и `git reset --hard origin/main`, а затем пересоздаёт окружение и контейнеры.

## Подключение в Infuse

Для подключения библиотеки в Infuse:

1. Откройте **Settings** → **Add Files** → **Other**.
2. Выберите **WebDAV**.
3. Укажите:
   - **Address** — IP-адрес сервера из `HOST_IP`;
   - **Port** — значение `WEBDAV_PORT`;
   - **Username** — значение `WEBDAV_USER`;
   - **Password** — значение `WEBDAV_PASSWORD`.
4. Сохраните подключение и добавьте источник в библиотеку.

После этого Infuse сможет индексировать `.strm`-файлы из каталога, опубликованного через WebDAV.

## Администрирование

Проверить состояние контейнеров:

```bash
cd /opt/infuse-media-server
docker compose ps
```

Посмотреть логи parser:

```bash
docker logs -f strm-parser
```

Остановить сервисы:

```bash
cd /opt/infuse-media-server
docker compose down
```

Запустить сервисы снова:

```bash
cd /opt/infuse-media-server
docker compose up -d
```

## Полезные URL

После установки скрипт выводит основные адреса:

- TorrServer UI: `http://HOST_IP:TORR_PORT`
- WebDAV URL: `http://HOST_IP:WEBDAV_PORT`

## Особенности

- Проект ориентирован на полностью контейнерный запуск без установки Python-окружения и cron на хосте.
- Библиотека для Infuse публикуется из локального каталога `./strm-library`, смонтированного в контейнер WebDAV.
- Parser зависит от доступности TorrServer и использует значения `HOST_IP` и `TORR_PORT` для генерации рабочих ссылок.

## Безопасность

- Файл `.env` создаётся скриптом с правами `600`.
- Доступ к WebDAV защищён логином и паролем, которые задаются во время установки.
- Поскольку WebDAV и TorrServer публикуются наружу через порты хоста, рекомендуется использовать сильный пароль и ограничивать внешний доступ сетевыми правилами.