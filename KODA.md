# KODA.md

Инструкционный контекст для работы AI-ассистента с этим монорепозиторием.

> Краткие правила для контрибьюторов и AI-агентов (структура, сборка, стиль, коммиты) — в [`AGENTS.md`](AGENTS.md). Этот файл — подробный контекст; при правке правил обновлять оба.

## Структура монорепозитория

```
ai-processing-specifications/
├── backend/              # Python/FastAPI-бэкенд (основная часть, описана ниже)
├── frontend/             # Nuxt 3 (Vue 3 + Tailwind v4, SSR) — см. «Frontend (frontend/)»
├── docs/
│   └── design-plan.md    # Мастер-план системы: модули, задачи, требования
├── srv/                  # Конфигурации сервисов для docker-compose
│   ├── nginx/            # nginx.conf + conf.d/default.conf (реверс-прокси)
│   └── pgbouncer/        # pgbouncer.env
├── .koda/skills/         # Скиллы Koda
├── docker-compose.yml    # postgres (pgvector), pgbouncer, redis, minio, backend, worker, frontend, nginx
├── .env / .env.example   # Переменные окружения compose (example — шаблон)
├── README.md             # Назначение системы и Tier-модель матчинга
├── AGENTS.md             # Краткие правила для контрибьюторов и AI-агентов
└── KODA.md               # Этот файл
```

⚠️ `backend/` и `frontend/` — **соседние** каталоги, а не вложенные. Все пути указывать от корня репозитория (`frontend/app/...`, `backend/app/...`); относительные пути в файловых инструментах могут резолвиться от `backend/`, из-за чего файлы `frontend/` «не находятся», а новая запись создаёт лишний `backend/frontend/`.

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

`pgbouncer.env` — параметры пула; `docker-compose.yml` подключает его через `env_file`, поэтому без файла сервис pgbouncer не запустится. Остальные параметры (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `LISTEN_ADDR`, `LISTEN_PORT`, `AUTH_TYPE`) задаются в самом `docker-compose.yml`.

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
| Frontend | Nuxt 3 (Vue 3, SSR, `srcDir: app/`) + Tailwind CSS v4, Pinia нет — состояние в композаблах |
| Инструменты | uv (менеджер зависимостей), ruff (линтер), pytest (тесты), npm/NVM (фронтенд) |
| Развёртывание | Docker + docker-compose (nginx как реверс-прокси, отдельный образ фронтенда) |

## Структура каталога backend

```
backend/
├── app/
│   ├── main.py            # Точка входа FastAPI (эндпоинт /health, подключение api_router и DI)
│   ├── worker/            # Celery-пакет: `celery_app` в __init__.py, таски в tasks.py, Redis Pub/Sub
│   ├── api/
│   │   └── v1/            # Роутеры FastAPI (route_class=DishkaRoute), только приём/ответ:
│   │                      #   auth.py — логин/refresh/logout/me;
│   │                      #   admin.py — прайс-листы, каталог, шаблоны КП;
│   │                      #   admin_access.py — пользователи, устройства, сессии (модуль 2);
│   │                      #   manager.py — спецификации, матчинг, SSE;
│   │                      #   deps.py — get_current_user/get_current_admin (вызываются из обработчиков,
│   │                      #   потому что dishka разбирает только FromDishka в сигнатуре эндпоинта)
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
│   ├── script.py.mako
│   └── versions/          # Файлы миграций: {YYYYMMDD}_{HHMMSS}-{rev}_{slug}.py
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
* `Device` — реестр fingerprint-устройств (`fingerprint_hash` — SHA-256, unique; `blocked`, `first_seen_at`, `last_seen_at`). Запись создаётся при входе (`AuthService.login`), `blocked` запрещает вход с устройства; сами отпечатки на сервере не хранятся.

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

## Frontend (`frontend/`)

Nuxt 3 (Vue 3, `<script setup>`) + Tailwind CSS v4 (`@tailwindcss/vite`). SSR включён, `srcDir: 'app/'`, конфигурация — `nuxt.config.ts`. **Pinia нет** — состояние в композаблах на `useState`.

* `app/app.vue` — корень приложения: `<NuxtLayout><NuxtPage /></NuxtLayout>`. Обёртка `NuxtLayout` обязательна — в собственном `app.vue` без неё `definePageMeta({ layout })` игнорируется и страницы рендерятся без шапки/панели.
* `app/assets/css/main.css` — `@import "tailwindcss"`, `@custom-variant dark`, палитра в токенах `--app-*` (`:root` / `html.dark`), блок `@theme inline` (обязателен `inline`: иначе Tailwind дублирует палитру в `--color-app-*`), общие классы компонентов.
* `app/pages/` — маршруты (auto-routing): `index.vue` (редирект по роли, `layout: false`), `login.vue`, `admin/*` (users, devices, sessions, pricelists, catalog, proposal-templates), `manager/specifications.vue` (загрузка + SSE), `manager/uploads.vue` (список ранее загруженных спецификаций).
* `app/layouts/default.vue` — шапка (переключатель темы, email, выход), страницы в один столбец (вход).
* `app/layouts/workspace.vue` — общий кабинет администратора и менеджера: тёмная панель навигации + рабочая область; подключается страницами `/admin/*` и `/manager/*` через `definePageMeta({ layout: 'workspace' })`. Различается только наполнение меню — пункты по роли берутся из `app/composables/useNavMenu.ts` (`ROLE_NAV`). Панель на отдельных токенах `--app-sidebar*`, которые намеренно не переопределены в `html.dark` (сайбар тёмный в обеих темах).
* `app/components/common/ThemeToggle.vue` — переключатель светлой/тёмной темы.
* `app/composables/` — `useAuth.ts` (сессия, роли, авто-refresh), `useNavMenu.ts` (пункты боковой панели по роли), `useTheme.ts` (класс `dark` + `localStorage`), `useFingerprint.ts` (thumbmarkjs).
* `app/plugins/` — `api.ts` ($fetch с cookie и интерцептором 401 → refresh → повтор), `theme.client.ts`, `thumbmark.client.ts`.
* `app/middleware/auth-guard.global.ts` — global middleware: сессия (`ensureAuth`), редирект гостя на `/login`, доступ к `/admin/**` (admin) и `/manager/**` (manager). Суффикс `.global` обязателен — без него Nuxt не подключает middleware к переходам.
* `Dockerfile` — `node:24-alpine`: `npm ci --legacy-peer-deps` (по `package-lock.json`) → `npm run build` → `node .output/server/index.mjs`, порт 3000. Версия Node в образе и локально (`.nvmrc`) должна совпадать.
* `.dockerignore` / `.gitignore` — `node_modules`, `.nuxt`, `.output` исключены из контекста сборки и из репозитория (без `.dockerignore` в образ попадали две копии зависимостей — 831 МБ вместо 449 МБ).
* `.nuxt/`, `.output/`, `node_modules/` — артефакты сборки: не редактировать и не коммитить.

Цвета брать только из токенов темы: в разметке — утилиты Tailwind (`bg-app-surface`, `text-app-muted`, …), в CSS-правилах — `var(--app-*)`; хардкод hex и палитры `neutral-*`/`white` не добавлять.

## Сборка и запуск

**Сборка и запуск — через docker-compose из корня репозитория** (`docker-compose.yml`, рядом нужен `.env`, шаблон `.env.example`). Локальные `uv run …` и `npm run …` — для линтинга, миграций и точной отладки.

```bash
# Из корня репозитория
docker compose build backend frontend   # образ backend используют сервисы backend и worker
docker compose up -d                    # postgres, pgbouncer, redis, minio, backend, worker, frontend, nginx
docker compose ps                       # статус сервисов и healthcheck
docker compose logs -f backend worker frontend
docker compose restart backend
docker compose down                     # без -v: тома postgres/minio — bind на каталоги хоста
```

* `backend` и `worker` монтируют `./backend/app:/app/app`, поэтому правки Python подхватываются `docker compose restart backend` без пересборки; `pyproject.toml`, `uv.lock` и `alembic/` копируются в образ — они требуют `docker compose build backend`.
* `frontend` собирается внутри образа (`npm run build`), bind-mount'а нет: после любых правок фронтенда — `docker compose build frontend`.
* Порты: nginx `:80` (`/api/` → backend, `/health` → backend, `/` → frontend), frontend `:3000`, pgbouncer `:5432`.
* `BACKEND_CONTAINER_COMMAND` в `.env` — аргументы uvicorn (`--workers N`; для разработки — `--reload`).

### Backend (`backend/`, uv)

Рабочий каталог — `backend/`.

```bash
uv sync                                                        # установка зависимостей (создаст .venv)
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000         # локальный запуск API
uv run celery -A app.worker worker --loglevel=info             # Celery-приложение объявлено в app/worker/__init__.py
uv run alembic upgrade head
uv run alembic revision -m "описание"                          # вручную, по правилам скилла alembic-create-revision
uv run ruff check .
uv run pytest                                                  # каталог backend/tests/ ещё не создан
```

### Frontend (`frontend/`)

Node.js установлен через **NVM** и отсутствует в PATH неинтерактивной оболочки (`npm: not found`) — перед npm-командами добавлять bin NVM в PATH:

```bash
export PATH="$HOME/.nvm/versions/node/$(ls "$HOME/.nvm/versions/node" | tail -1)/bin:$PATH"
node -v && npm -v
```

Рабочий каталог — `frontend/`:

```bash
npm ci --legacy-peer-deps         # установка по package-lock.json — как в образе
npm run dev                       # nuxt dev → http://localhost:3000
npm run build                     # production-сборка в .output/
npm run preview                   # nuxt preview
```

⚠️ Версия Node фиксируется в двух местах и должна совпадать: `.nvmrc` (локально) и `FROM node:24-alpine` (образ). `package-lock.json` коммитится — он обязателен для сборки образа (`npm ci`). `--legacy-peer-deps` нужен из-за конфликтующих peer-зависимостей в стеке Nuxt. Тестов, линтера и typecheck-скриптов в `package.json` нет: проверка фронтенда = успешная сборка.

Примечания к Dockerfile:

* Базовый образ `python:3.13-slim` + системные библиотеки pango/cairo/gdk-pixbuf (нужны WeasyPrint) и curl (для проверок из контейнера; `healthcheck` в compose объявлен у postgres, redis и minio, у backend — нет).
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
