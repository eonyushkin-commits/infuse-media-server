#!/usr/bin/env bash

# ==============================================================================
# СТРОГИЙ РЕЖИМ (Strict Mode)
# ==============================================================================
set -euo pipefail

# ==============================================================================
# КОНСТАНТЫ И ЦВЕТА
# ==============================================================================
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly CYAN='\033[0;36m'
readonly NC='\033[0m'

readonly INSTALL_DIR="/opt/infuse-media-server"
readonly REPO_URL="https://github.com/eonyushkin-commits/infuse-media-server.git"

# ==============================================================================
# ФУНКЦИИ ЛОГИРОВАНИЯ
# ==============================================================================
log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# ==============================================================================
# ОБРАБОТЧИК ПРЕРЫВАНИЙ И ОШИБОК
# ==============================================================================
cleanup() {
    local exit_code=$?
    [ $exit_code -ne 0 ] && log_err "Установка прервана (код: $exit_code)."
}
trap cleanup EXIT
trap 'exit 130' INT # Код 130 для Ctrl+C
trap 'exit 143' TERM # Код 143 для SIGTERM

# ==============================================================================
# ПРОВЕРКА ОКРУЖЕНИЯ
# ==============================================================================
check_requirements() {
    log_info "Проверка системных требований..."

    if [ "$EUID" -ne 0 ]; then
        log_err "Этот скрипт должен быть запущен с правами root (sudo)."
        exit 1
    fi

    local deps=("git" "docker" "curl")
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" >/dev/null 2>&1; then
            log_err "Утилита '$dep' не установлена. Пожалуйста, установите её."
            exit 1
        fi
    done

    # Fail-fast проверка Docker Compose
    if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
        log_err "Docker Compose не найден (ни v1, ни v2)."
        exit 1
    fi
}

# ==============================================================================
# ЗАГРУЗКА ИЛИ ОБНОВЛЕНИЕ КОДА
# ==============================================================================
fetch_repository() {
    # Валидация: заглушка в REPO_URL не была заменена
    if [[ "$REPO_URL" == *"ВАШ_ЛОГИН"* ]]; then
        log_err "Замените REPO_URL в скрипте на адрес своего репозитория."
        exit 1
    fi

    if [ -d "$INSTALL_DIR/.git" ]; then
        log_info "Проект уже существует в $INSTALL_DIR. Выполняю обновление..."
        log_warn "Все локальные изменения кода в $INSTALL_DIR будут ПЕРЕЗАПИСАНЫ (кроме .env)."
        read -rp "Продолжить? [y/N]: " confirm
        [[ "$confirm" =~ ^[yY]([eE][sS])?$ ]] || { log_info "Обновление отменено."; return 0; }

        (cd "$INSTALL_DIR" && git fetch --all && git reset --hard origin/main)
    else
        log_info "Клонирование репозитория в $INSTALL_DIR..."
        git clone -q "$REPO_URL" "$INSTALL_DIR"
    fi
}

# ==============================================================================
# ГЕНЕРАЦИЯ КОНФИГУРАЦИИ (.env И NGINX PROXY)
# ==============================================================================
configure_env() {
    local env_file="$INSTALL_DIR/.env"

    if [ -f "$env_file" ]; then
        log_warn "Файл .env уже существует. Пересоздать его? [y/N]"
        read -rp "Ваш выбор: " response
        if [[ ! "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
            log_info "Сохраняем текущую конфигурацию."

            # Строгая валидация формата .env перед загрузкой
            grep -vE '^\s*(#|$)' "$env_file" | grep -qvE '^[A-Z_][A-Z0-9_]*=' && \
            { log_err "Файл .env содержит строки неверного формата. Исправьте его или удалите для пересоздания."; exit 1; } || true

            set -a; source "$env_file"; set +a
            
            # Если .env не пересоздаётся, всё равно нужно сгенерировать конфиги Nginx для обновления
            log_info "Обновление ключей доступа для TorrServer..."
            docker run --rm httpd:alpine htpasswd -bn "$WEBDAV_USER" "$WEBDAV_PASSWORD" > "$INSTALL_DIR/.htpasswd"
            chmod 600 "$INSTALL_DIR/.htpasswd"

            cat > "$INSTALL_DIR/nginx.conf" << 'EOF'
server {
    listen 80;
    location / {
        auth_basic "Restricted Area";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://torrserver:8090;
        proxy_set_header Host $host;
    }
}
EOF
            return 0
        fi
    fi

    log_info "Настройка конфигурации..."

    # --- WebDAV порт ---
    read -rp "Укажите порт для WebDAV (по умолчанию 8080): " WEBDAV_PORT
    WEBDAV_PORT=${WEBDAV_PORT:-8080}

    if ! [[ "$WEBDAV_PORT" =~ ^[0-9]+$ ]] || [ "$WEBDAV_PORT" -lt 1 ] || [ "$WEBDAV_PORT" -gt 65535 ]; then
        log_err "Некорректный порт: $WEBDAV_PORT. Порт должен быть числом от 1 до 65535."
        exit 1
    fi

    # --- WebDAV учётные данные ---
    read -rp "Укажите логин для WebDAV и TorrServer (по умолчанию admin): " WEBDAV_USER
    WEBDAV_USER=${WEBDAV_USER:-admin}

    read -rsp "Укажите пароль для WebDAV и TorrServer: " WEBDAV_PASSWORD
    echo
    [ -z "$WEBDAV_PASSWORD" ] && { log_err "Пароль не может быть пустым."; exit 1; }

    # --- TorrServer: IP и порт ---
    log_info "Определение внешнего IP-адреса сервера..."
    AUTO_IP=$(curl -s --connect-timeout 5 ifconfig.me 2>/dev/null || echo "")
    if ! echo "$AUTO_IP" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
        AUTO_IP="127.0.0.1"
        log_warn "Не удалось определить внешний IP автоматически. Используется $AUTO_IP."
    fi

    read -rp "Укажите внешний IP-адрес сервера (по умолчанию $AUTO_IP): " HOST_IP
    HOST_IP=${HOST_IP:-$AUTO_IP}

    # Генерируем случайный порт в диапазоне 10000-60000
    AUTO_TORR_PORT=$(shuf -i 10000-60000 -n 1)
    read -rp "Укажите публичный порт для TorrServer (по умолчанию $AUTO_TORR_PORT): " TORR_PORT
    TORR_PORT=${TORR_PORT:-$AUTO_TORR_PORT}

    if ! [[ "$TORR_PORT" =~ ^[0-9]+$ ]] || [ "$TORR_PORT" -lt 1 ] || [ "$TORR_PORT" -gt 65535 ]; then
        log_err "Некорректный порт: $TORR_PORT. Порт должен быть числом от 1 до 65535."
        exit 1
    fi
    # Проверяем что порт не занят
    if ss -tlun | grep -q ":${TORR_PORT} "; then
        log_err "Порт $TORR_PORT уже занят. Запустите установку заново или укажите другой порт."
        exit 1
    fi

    # --- Запись .env ---
    touch "$env_file" && chmod 600 "$env_file"
    cat > "$env_file" <<EOF
WEBDAV_PORT=$WEBDAV_PORT
WEBDAV_USER=$WEBDAV_USER
WEBDAV_PASSWORD=$WEBDAV_PASSWORD
HOST_IP=$HOST_IP
TORR_PORT=$TORR_PORT
EOF

    # === НОВЫЙ БЛОК ГЕНЕРАЦИИ NGINX ===
    log_info "Генерация ключей доступа для TorrServer proxy..."
    docker run --rm httpd:alpine htpasswd -bn "$WEBDAV_USER" "$WEBDAV_PASSWORD" > "$INSTALL_DIR/.htpasswd"
    chmod 600 "$INSTALL_DIR/.htpasswd"

    cat > "$INSTALL_DIR/nginx.conf" << 'EOF'
server {
    listen 80;
    location / {
        auth_basic "Restricted Area";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://torrserver:8090;
        proxy_set_header Host $host;
    }
}
EOF
    # ==================================
}

# ==============================================================================
# ЗАПУСК СЕРВИСОВ И ВЫВОД ИНФОРМАЦИИ
# ==============================================================================
start_services() {
    log_info "Запуск Docker-контейнеров..."
    cd "$INSTALL_DIR"
    
    if docker compose version >/dev/null 2>&1; then
        docker compose up -d --build
    else
        docker-compose up -d --build
    fi

    echo ""
    log_success "Установка успешно завершена!"
    echo "-------------------------------------------------------"
    log_info "TorrServer UI: http://${HOST_IP}:${TORR_PORT}"
    log_info "WebDAV URL: http://${HOST_IP}:${WEBDAV_PORT}"
    log_info "Логин для входа (WebDAV и TorrServer): ${WEBDAV_USER}"
    echo "-------------------------------------------------------"
    log_info "Логи парсера: docker logs -f strm-parser"
}

# ==============================================================================
# ГЛАВНЫЙ БЛОК ВЫПОЛНЕНИЯ
# ==============================================================================
main() {
    echo -e "${BLUE}=== Установка Infuse Media Server ===${NC}"
    check_requirements
    fetch_repository
    configure_env
    start_services
}

main