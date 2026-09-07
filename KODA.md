# KODA.md

Инструкционный контекст для работы AI-ассистента с этим монорепозиторием.

## Структура монорепозитория

```
ai-processing-specifications/
├── backend/              # Python/FastAPI-бэкенд (основная часть, описана ниже)
├── docs/
│   └── design-plan.md    # Мастер-план системы: модули, задачи, требования
├── srv/                  # Конфигурации сервисов для docker-compose
│   ├── nginx/            # nginx.conf + conf.d/default.conf (реверс-прокси)
│   └── pgbouncer/        # pgbouncer.env (файл отсутствует — TODO)
├── .koda/skills/         # Скиллы Koda
├── docker-compose.yml    # Поднимает postgres (pgvector), pgbouncer, redis, minio, backend, worker, nginx
└── KODA.md               # Этот файл
```

## Документация (docs/)

`docs/design-plan.md` — мастер-план разработки системы (v3, Modern Stack). Ключевое содержимое:

* **Модуль 1** — инфраструктура: uv, docker-compose, схема БД (совпадает с реализованными моделями в `backend/app/models/models.py`).
* **Модуль 2** — безопасность: stateful JWT (access 15 мин / refresh 7 дней) с привязкой к fingerprint браузера (thumbmarkjs), выдача только через `Set-Cookie` (HttpOnly), серверные сессии в Redis (`session:{user_id}:{fingerprint_hash}`), blacklist отозванных access-токенов (`revoked:{jti}`).
* **Модуль 3** — панель администратора:
  * Загрузка прайс-листов в MinIO: потоковая загрузка (без чтения в память, `SpooledTemporaryFile`, лимит 50 МБ).
  * Превью первых 50 строк через `ExcelPreviewService` (openpyxl `read_only`).
  * LLM-предсказание маппинга колонок: промпт содержит заголовки **и** первые 5 строк данных (через `LlmService`/litellm: по умолчанию локальная `ollama/qwen2.5:7b`, опционально облачный `gpt-4o-mini`).
  * Подтверждение/редактирование маппинга админом: `POST /admin/pricelists/{upload_id}/confirm` (обновляет `column_mapping`, меняет статус на `processing`).
  * Фоновая векторизация каталога: Celery-таска `catalog.vectorize`, батчи по 500 строк, `EmbeddingService` (`intfloat/multilingual-e5-base`, 768-dim), сохранение в `CatalogItem`.
* **Модуль 4** — Matching Engine: сервис `match_row(raw_name, sku)` с трёхуровневым алгоритмом (Tier 1 — словарь по SHA-256; Tier 2 — векторный поиск `<=>`, топ-5 при cosine score ≥ 0.70; Tier 3 — unmatched).
* **Модуль 5** — рабочее место менеджера: загрузка спецификаций, асинхронный процессинг Celery, real-time обновления через Redis Pub/Sub (`channel: spec_{id}`) и SSE (`GET /api/v1/manager/specifications/{id}/stream`).
* **Модуль 6** — frontend на Nuxt 3: middleware защиты роутов, интерцепторы `ofetch` (cookies, авто-refresh при 401), UI с цветовым кодированием результатов матчинга.
* **Модуль 7** — генератор КП: экспорт `GET /api/v1/manager/specifications/{id}/export?format=pdf|xlsx` (WeasyPrint + Jinja2 / openpyxl).

План — первичный источник требований; при расхождении с кодом приоритет у кода, а устаревшие пункты плана стоит помечать/обновлять.

## Конфигурации сервисов (srv/)

### nginx (`srv/nginx/`)

* `nginx.conf` — базовый http-блок (worker_processes auto, keepalive 65, логи).
* `conf.d/default.conf` — единственный server на порту 80:
  * `client_max_body_size 100m` — под загрузку Excel-файлов.
  * Резолв upstream `http://backend:8000` через Docker DNS на каждый запрос (переменная + `resolver 127.0.0.11`).
  * Проксирует все заголовки (`Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`).
  * **SSE-настройки**: `proxy_buffering off`, `proxy_cache off`, `proxy_read_timeout 3600s` — при добавлении новых стриминговых эндпоинтов учитывать эти ограничения.

### pgbouncer (`srv/pgbouncer/`)

Директория пуста — `docker-compose.yml` ожидает файл `srv/pgbouncer/pgbouncer.env` (без него сервис pgbouncer не запустится). TODO: создать файл с параметрами подключения.

## Скиллы Koda (.koda/skills/)

* `alembic-create-revision` — правила создания Alembic-миграций. Ключевые требования:
  * Создавать миграцию **без** autogenerate: `alembic revision -m "{message}"`, вручную.
  * Одна миграция — изменения только одной таблицы.
  * Имена индексов/ключей/ограничений задавать через `op.f(...)`.
  * Русские комментарии для каждой таблицы и каждого поля.
  * Именование: `pk_{table}`, `fk_{table}_{field}_{remote_table}`, `uq_{table}_{fields...}`, `ix_{table}_{fields...}`, `tp_{type_name}`.
  * Для Enum — Python-класс с именем типа `tp_{class_name_snake_case}` (например, `Enum(UserRole, name="tp_user_role")`).
  * `op.create_table` — с `sa.PrimaryKeyConstraint`; остальные ограничения и индексы — отдельными вызовами `op.create_*`.

⚠️ Существующие модели в `backend/app/models/models.py` используют имена Enum-типов без префикса `tp_` (например, `user_role`, а не `tp_user_role`) — при создании миграций следовать правилам скилла и привести именование к единому виду.

## Обзор проекта

`backend` — серверная часть AI-системы обработки спецификаций и генерации коммерческих предложений (КП).

Назначение системы:

* Администраторы загружают прайс-листы, из которых формируется номенклатура каталога (`CatalogItem`).
* Менеджеры загружают спецификации клиентов, строки которых сопоставляются с каталогом (матчинг).
* Матчинг трёхуровневый (Tier-модель):
  * **Tier 1 (`auto`)** — точное совпадение по словарю подтверждённых совпадений (`HistoricalMatch`, ключ — SHA-256 хэш исходного наименования).
  * **Tier 2 (`top_n`)** — варианты из векторного поиска по эмбеддингам (pgvector, HNSW-индекс, косинусная дистанция).
  * **Tier 3 (`unmatched`)** — не найдено; строки ожидают ручного подтверждения/исключения менеджером.

### Технологический стек

| Компонент | Технология |
|---|---|
| Язык | Python ≥ 3.13 |
| Веб-фреймворк | FastAPI + Uvicorn |
| БД | PostgreSQL 17 с расширением pgvector (через PgBouncer) |
| ORM / миграции | SQLAlchemy 2 (asyncio, mapped_column) + Alembic (async engine) |
| Драйвер БД | psycopg 3 (`postgresql+psycopg://...`) |
| Очередь задач | Celery + Redis (брокер и бэкенд результатов) |
| Хранилище файлов | MinIO / S3 |
| Обработка файлов | openpyxl (Excel), WeasyPrint (PDF) |
| AI — эмбеддинги | `sentence-transformers` + `intfloat/multilingual-e5-base` локально на CPU (768-dim), Singleton `EmbeddingService` |
| AI — LLM | `litellm` (единый слой): облачный `openai/gpt-4o-mini` или локальная Ollama `ollama/qwen2.5:7b` — переключение через `LLM_PROVIDER` |
| Конфигурация | pydantic-settings, `.env` |
| Инструменты | uv (менеджер зависимостей), ruff (линтер), pytest (тесты) |
| Развёртывание | Docker + docker-compose (nginx как реверс-прокси) |

## Структура каталога backend

```
backend/
├── app/
│   ├── main.py            # Точка входа FastAPI (эндпоинт /health, подключение api_router и DI)
│   ├── worker.py          # Celery-приложение (брокер/бэкенд — Redis)
│   ├── api/
│   │   └── v1/            # Роутеры FastAPI (route_class=DishkaRoute), только приём/ответ
│   ├── core/
│   │   └── config.py      # pydantic-settings: группы настроек с env-префиксами
│   ├── db/
│   │   ├── base.py        # DeclarativeBase + naming_convention для Alembic
│   │   └── session.py     # Async engine, session factory
│   ├── di/                # Контейнер dishka: провайдеры настроек, сессий, репозиториев, сервисов
│   ├── models/
│   │   └── models.py      # Все ORM-модели и enum-ы
│   ├── repositories/      # Репозитории: вся работа с БД (SQL-запросы)
│   ├── schemas/           # Pydantic-схемы запросов/ответов API
│   └── services/          # Классы бизнес-логики (services layer)
├── alembic/
│   ├── env.py             # Async-миграции; DSN берётся из Settings, не из alembic.ini
│   └── script.py.mako
├── alembic.ini
├── pyproject.toml         # Зависимости проекта (uv)
├── uv.lock
└── Dockerfile             # python:3.13-slim + системные либы WeasyPrint + лимиты потоков ML (ENV)
```

### Ключевые модели (`app/models/models.py`)

* `User` — пользователи, роли: `admin`, `manager`.
* `CatalogItem` — номенклатура каталога (уникальность по паре `sku`+`name`, поле `embedding Vector(768)` с HNSW-индексом под `vector_cosine_ops`); создаётся фоновой Celery-таской `catalog.vectorize` из прайс-листов.
* `PriceListUpload` / `SpecificationUpload` — сессии загрузки файлов (статусы: `pending → mapping_predicted → processing → completed | failed`). `mapping_predicted` — LLM предсказал маппинг, ожидает подтверждения админом.
* `SpecificationRow` — строка спецификации с результатом матчинга (`MatchType`, `RowStatus`: `pending / matched / confirmed / excluded`).
* `HistoricalMatch` — словарь подтверждённых совпадений для Tier-1 (`raw_name_hash` — SHA-256, unique).

### Конфигурация (`app/core/config.py`)

Настройки агрегируются классом `Settings` через `get_settings()` (кэшируется `@lru_cache`). Каждая группа читает env-переменные со своим префиксом из `.env` (или `../.env`):

* `PROJECT_*` — окружение (`environment`, по умолчанию `loc`), домен, схема, `data_dir` (по умолчанию `/data`).
* `POSTGRES_*` — параметры БД; вычисляемое поле `dsn` для psycopg3.
* `SQLALCHEMY_*` — пул соединений (pool_size, max_overflow, pool_pre_ping и т.д.).
* `REDIS_*` — параметры Redis; вычисляемое поле `url`.
* `MINIO_*` — MinIO/S3 (порт 9000).
* `BACKEND_*` — debug, число воркеров, порт, `api_prefix` (по умолчанию `/api/v1`).
* `CORS_ORIGINS` — список разрешённых origin (без префикса).
* `JWT_*` — параметры JWT и auth-кук (секрет, сроки жизни, имена кук, secure).
* `EMBEDDING_*` — локальная модель эмбеддингов (`EMBEDDING_MODEL_NAME`, `EMBEDDING_DEVICE`, `EMBEDDING_DIM`).
* `LLM_*` — LLM через litellm: `LLM_PROVIDER` (`openai` | `ollama`), имена моделей, `LLM_OLLAMA_BASE_URL`, параметры генерации.
* `OPENAI_*` — API-ключ OpenAI (нужен только при `LLM_PROVIDER=openai`).
* `OMP/MKL/OPENBLAS/NUMEXPR_NUM_THREADS` — ограничение потоков математических вычислений (CPU-режим ML, по умолчанию 4; также заданы в Dockerfile).
* `HF_DATA_DIR` — каталог кэша моделей Hugging Face на хосте; в контейнеры backend/worker монтируется как volume `hfdata` и задаётся `HF_HOME`.

## Сборка и запуск

Пакетный менеджер — **uv**. Репозиторий — часть монорепозитория: корневой `docker-compose.yml` (на уровень выше) поднимает postgres (pgvector), pgbouncer, redis, minio, backend, celery-worker и nginx.

```bash
# Установка зависимостей (создаст venv)
uv sync

# Запуск API локально
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# Запуск Celery-воркера
uv run celery -A app.worker.celery_app worker --loglevel=info

# Миграции Alembic (DSN из переменных окружения)
uv run alembic upgrade head
uv run alembic revision -m "описание"  # вручную, по правилам скилла alembic-create-revision

# Линтинг
uv run ruff check .

# Тесты
uv run pytest
```

Docker:

```bash
# Из корня монорепозитория (там же нужен .env)
docker compose build backend
docker compose up -d
```

Примечания к Dockerfile:

* Базовый образ `python:3.13-slim` + системные библиотеки pango/cairo/gdk-pixbuf (нужны WeasyPrint) и curl (healthcheck).
* Зависимости ставятся через `uv sync --frozen --no-dev --no-install-project`; venv размещается в `/opt/venv`, чтобы bind-mount исходников (`./backend/app:/app/app`) его не затирал.

### Проверка работоспособности

* `GET /health` — возвращает `{"status": "ok"}`.

## Правила разработки

* **Архитектура кода**:
  * По максимуму использовать классы, по минимуму отдельные функции — особенно в сервисном слое.
  * Паттерн **repository**: работа с БД инкапсулируется в репозиториях (`app/repositories/`), обработчики и сервисы не пишут SQL-запросы напрямую.
  * Паттерн **services layer**: бизнес-логика живёт в классах-сервисах (`app/services/`); обработчики FastAPI только принимают запрос, вызывают сервис и формируют ответ.
  * **Внедрение зависимостей** — через контейнер `dishka` (`app/di/`): настройки, сессии БД, репозитории и сервисы предоставляются провайдерами, а не создаются вручную в обработчиках.
  * Для каждого `APIRouter` указывать параметр `route_class=DishkaRoute` (из `dishka.integrations.fastapi`), а зависимости в обработчиках объявлять через `FromDishka[...]` / `Annotated[..., FromDishka()]`.
* **Сообщения**: все пользовательские тексты (ошибки API, статусы, логи) хранить в едином реестре `app/core/messages.py` — класс-константа на домен (`AuthMessages`, `CommonMessages`, ...); в коде не допускать строковых литералов сообщений. Для сообщений с параметрами — статические методы, возвращающие отформатированную строку.
* **Стиль кода**: ruff с `line-length = 100`, `target-version = py313`. Использовать современный синтаксис: `X | None` вместо `Optional[X]`, type-hints через `Mapped[...]` / `mapped_column` в ORM.
* **Язык**: код и идентификаторы — на английском; комментарии и docstrings — на русском.
* **Модели БД**:
  * Все модели наследуются от `app.db.base.Base` и объявляются в `app/models/models.py`.
  * Первичные ключи — `UUID(as_uuid=True)` с генерацией `uuid4` на стороне приложения.
  * Временные метки — `DateTime(timezone=True)` с `server_default=func.now()`.
  * Соблюдать `naming_convention` из `base.py` (стабильные имена constraint'ов для миграций).
* **Миграции**: создавать вручную по правилам скилла `alembic-create-revision` (`alembic revision -m "..."`, без `--autogenerate`); env.py сам подтягивает DSN из настроек. ⚠️ Каталог `alembic/` копируется в образ Docker (не bind-mount) — после изменения миграций/моделей нужна пересборка `docker compose build backend` перед применением.
* **Конфигурация**: только через переменные окружения / `.env`; новые настройки добавлять в соответствующую группу в `config.py` с env-префиксом, `extra="ignore"`.
* **Сессии БД**: `AsyncSession` предоставляется через dishka-провайдер (на основе factory из `app.db.session`); сессии async (`AsyncSession`), `expire_on_commit=False`. Прямое использование `get_db_session` в обработчиках не рекомендуется — доступ к данным через репозитории.
* **Тесты**: pytest (в dev-зависимостях); при добавлении функциональности добавлять тесты.
* **Фоновые задачи**: долгие операции (парсинг прайс-листов, эмбеддинги, матчинг) — через Celery-таски, а не в обработчиках FastAPI.
