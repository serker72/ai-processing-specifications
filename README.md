# AI-система обработки спецификаций и генерации КП

## Назначение системы

Система автоматизирует подготовку коммерческих предложений (КП) из спецификаций
клиентов. Полный цикл:

1. **Администратор** загружает прайс-лист поставщика (Excel) → система читает превью,
   LLM предсказывает маппинг колонок → админ подтверждает маппинг → фоновая задача
   строит номенклатуру каталога (`CatalogItem`) с эмбеддингами.
2. **Менеджер** загружает спецификацию клиента (Excel) → LLM предсказывает маппинг
   (наименование, количество, единица, цена) → фоновая задача прогоняет каждую строку
   через Matching Engine и сопоставляет её с каталогом.
3. Менеджер на рабочем столе разбирает спорные строки (подтверждает/исключает, выбирает
   из кандидатов), после чего формирует **КП в PDF** по подтверждённым строкам с расчётом
   сумм и НДС; история КП доступна отдельно.

## Возможности

**Администрирование (роль `admin`)**

- Загрузка прайс-листов, превью и подтверждение маппинга колонок (LLM-предсказание с
  ручной правкой), история загрузок со статусами, фильтром и пагинацией; повторная
  обработка упавших загрузок.
- Каталог номенклатуры: постраничный список с поиском и инлайн-правкой позиций
  (наименование/единица/цена; при смене наименования эмбеддинг пересчитывается).
- Шаблоны КП: загрузка HTML, инлайн-правка названия/даты, удаление, выбор действующего
  шаблона по дате начала.
- Системные настройки КП (реквизиты продавца, ставка и режим НДС).
- Безопасность: управление пользователями (смена роли), реестр fingerprint-устройств
  (блокировка/разблокировка), активные сессии (принудительный отзыв).

**Рабочее место менеджера (роль `manager`)**

- Загрузка спецификаций клиентов с выбором/созданием клиента.
- Реальное время: ход обработки транслируется через SSE (Server-Sent Events) с
  устойчивым переподключением.
- Рабочий стол строки спецификации: пагинация, цветовое кодирование результата матчинга,
  подтверждение (текущая позиция или кандидат из ТОП-N векторного поиска), исключение.
- Формирование и скачивание КП в PDF, история КП менеджера.

## Матчинг: трёхуровневая модель (Tier)

- **Tier 1 (`auto`)** — точное совпадение по словарю подтверждённых совпадений
  (`HistoricalMatch`, ключ — SHA-256 хэш исходного наименования), O(1).
- **Tier 2 (`top_n`)** — векторный поиск по эмбеддингам (pgvector, HNSW-индекс,
  косинусная дистанция `<=>`), ТОП-5 кандидатов при score ≥ 0.70.
- **Tier 3 (`unmatched`)** — совпадение не найдено; строка ожидает ручного решения
  менеджера.

Подтверждение строки менеджером пополняет словарь Tier-1, поэтому следующая строка с
тем же наименованием находится мгновенно.

## Архитектура

```
                      ┌───────────────┐
   браузер  ───────►  │ nginx :80     │  /api/ → backend, / → frontend (SSR)
                      └──────┬────────┘
                             │
              ┌──────────────┼───────────────┐
              ▼              ▼               ▼
        ┌──────────┐   ┌──────────┐   ┌──────────────┐
        │ frontend │   │ backend  │   │   worker     │
        │ Nuxt 3   │   │ FastAPI  │   │ Celery       │
        └──────────┘   └────┬─────┘   └──────┬───────┘
                            │                │
             ┌──────────────┼────────────────┼─────────────┐
             ▼              ▼                ▼             ▼
        PostgreSQL 17    Redis 7         MinIO/S3     Ollama / OpenAI
        (+pgvector)   (сессии, брокер,   (файлы,      (LLM, опц.)
                       Pub/Sub, blacklist) PDF)
```

- **backend** — FastAPI-приложение (REST API, авторизация, SSE-поток обработки).
- **worker** — Celery-воркер: векторизация каталога, обработка спецификаций, пересчёт
  эмбеддингов.
- **frontend** — Nuxt 3 (SSR) с ролевыми интерфейсами администратора и менеджера.
- **nginx** — единая точка входа: проксирует `/api/` и `/health` на backend, `/` — на
  frontend; для SSE отключена буферизация.
- **PostgreSQL + pgvector** — данные и векторный поиск; **Redis** — серверные сессии,
  blacklist JWT, брокер Celery и Pub/Sub для SSE; **MinIO** — исходные Excel-файлы,
  HTML-шаблоны и сгенерированные PDF.

## Технологический стек

| Компонент | Технология |
|---|---|
| Язык backend | Python ≥ 3.13, менеджер зависимостей `uv` |
| Веб-фреймворк | FastAPI + Uvicorn, DI через `dishka` |
| БД | PostgreSQL 17 + pgvector (через PgBouncer) |
| ORM / миграции | SQLAlchemy 2 (async) + Alembic |
| Драйвер БД | psycopg 3 |
| Очередь задач | Celery + Redis |
| Хранилище файлов | MinIO (S3) |
| Обработка файлов | openpyxl (Excel), WeasyPrint + Jinja2 (PDF) |
| Эмбеддинги | `sentence-transformers`, `intfloat/multilingual-e5-base` (768-dim, CPU) |
| LLM | `litellm`: локальная Ollama `qwen2.5:7b` (по умолчанию) или OpenAI `gpt-4o-mini` |
| Frontend | Nuxt 3 (Vue 3, SSR, `srcDir: app/`) + Tailwind CSS v4, состояние в композаблах |
| Инфраструктура | Docker + docker-compose, nginx как реверс-прокси |

## Роли и доступ

Ролевая модель — `admin` и `manager`. Роль хранится в БД и возвращается эндпоинтом
`GET /api/v1/auth/me`; клиентские флаги не являются основанием для доступа — реальная
проверка ролей выполняется на backend. Frontend-маршруты защищены глобальным middleware
(`/admin/**` — только admin, `/manager/**` — только manager).

## Аутентификация и безопасность

- Вход `POST /api/v1/auth/login` принимает `email`, `password` и `fingerprint` устройства
  (ThumbmarkJS). Токены выдаются **только** через `HttpOnly`-куки: access (15 мин) и
  refresh (7 дней), в payload вшит хэш fingerprint.
- Refresh-токен хранится в Redis (`session:{user_id}:{fingerprint_hash}`, TTL 7 дней) и
  ротируется; `jti` отозванных токенов попадает в blacklist. Смена fingerprint или
  отзыв сессии/блокировка устройства делают токен недействительным.
- Refresh-кука — `SameSite=Strict`, access-кука — `SameSite=Lax`.
- Все application-логи backend и worker — структурированный JSON; backend добавляет
  `request_id` (заголовок `X-Request-ID` от nginx либо сгенерированный), worker —
  `upload_id` обрабатываемой загрузки.

## Модель данных (ключевое)

- `User` — пользователи и роли (`admin`/`manager`).
- `CatalogItem` — номенклатура каталога: `sku`, `name`, `unit`, `price`, `embedding
  Vector(768)` (HNSW, `vector_cosine_ops`); уникальность пары `sku`+`name`.
- `PriceListUpload` / `SpecificationUpload` — загрузки файлов со статусами
  `pending → mapping_predicted → processing → completed | failed`.
- `SpecificationRow` — строка спецификации с результатом матчинга (`MatchType`,
  `RowStatus`: `pending`/`processing`/`matched`/`unmatched`/`confirmed`/`excluded`).
- `HistoricalMatch` — словарь Tier-1 (`raw_name_hash` SHA-256, unique).
- `Device` — реестр fingerprint-устройств (`fingerprint_hash` SHA-256, `blocked`, метки
  времени); хранится только хэш.
- `Proposal` / `ProposalDocument` / `ProposalCounter` — КП, версии PDF и нумерация
  `КП-{год}-{5 цифр}`.
- `Client`, `AppSettings`, `ProposalTemplate` — клиенты, системные настройки (singleton),
  HTML-шаблоны КП.

## Структура репозитория

```
backend/    FastAPI + Celery: app/ (api, services, repositories, models, schemas, worker, core, di)
frontend/   Nuxt 3 (srcDir: app/): pages/, layouts/, composables/, plugins/, middleware/
srv/        конфиги nginx и pgbouncer
docs/       планы (design-plan.md — master-план, plan-pricelist-mapping.md — ход работ)
docker-compose.yml   все сервисы
```

## Конфигурация

Все переменные окружения — в `.env` (шаблон — `.env.example`). Настройки группируются по
префиксам (`PROJECT_*`, `POSTGRES_*`, `REDIS_*`, `MINIO_*`, `BACKEND_*`, `JWT_*`,
`CORS_ORIGINS`, `EMBEDDING_*`, `LLM_*`, `OPENAI_*`). Новые переменные добавлять в
`.env.example` и в соответствующую группу `backend/app/core/config.py`.

## Запуск

```bash
# из корня репозитория (нужен .env)
docker compose build backend frontend
docker compose up -d
docker compose ps
docker compose logs -f backend worker frontend
```

Правки `backend/app` подхватываются `docker compose restart backend` (bind-mount);
изменения `pyproject.toml`/`uv.lock`/`alembic/` и любые правки фронтенда требуют
пересборки соответствующего образа.

## Проверка и разработка

Backend (рабочий каталог `backend/`, `uv`):

```bash
uv sync
uv run ruff check .
uv run alembic upgrade head
uv run pytest          # каталог backend/tests/ ещё не создан
```

Frontend (рабочий каталог `frontend/`, Node через NVM): `npm ci --legacy-peer-deps`,
`npm run dev`, `npm run build` (успешная сборка — основной критерий проверки, тестов и
линтера у фронтенда нет).

## Прод-развёртывание: чеклист безопасности

Приложение `fail-fast` проверяет часть настроек на старте: при `PROJECT_ENVIRONMENT != loc`
оно **не запустится** с дефолтным секретом или с auth-куками без флага `Secure`
(`Settings._validate_safety`, `backend/app/core/config.py`).

Обязательно перед прод-запуском:

- **`PROJECT_ENVIRONMENT`** — любое значение кроме `loc` (включает строгую валидацию).
- **`JWT_SECRET_KEY`** — уникальный, не `change-me-in-production`
  (`python -c "import secrets; print(secrets.token_hex(32))"`). Ротация секрета обрывает
  активные сессии: refresh-токены хранятся в Redis, но подписываются старым ключом.
- **`JWT_COOKIE_SECURE=True`** — куки передаются только по HTTPS.
- **`JWT_COOKIE_DOMAIN`** — домен auth-кук. Пусто = домен запроса (штатный случай, когда
  frontend и API отдаются с одного origin через nginx). Задавать явно (`.example.com`),
  только если frontend и API разнесены по поддоменам; иначе браузер не сочтёт куки
  same-site и авторизация сломается.
- **`BACKEND_BASE_URL` и `CORS_ORIGINS`** — домен `BACKEND_BASE_URL` должен присутствовать
  среди origin'ов `CORS_ORIGINS`. Несовпадение не блокирует старт, но пишет предупреждение
  (`ConfigMessages.cors_domain_mismatch`): это риск, что браузер не отправит auth-куки.
- **`NUXT_PUBLIC_API_BASE`** (в `docker-compose.yml` = `BACKEND_BASE_URL` + `BACKEND_API_PREFIX`)
  должен указывать на тот же сайт, что и origin фронтенда.

Auth-куки выдаются только как `HttpOnly`. Refresh-кука имеет `SameSite=Strict` (вызывается
только XHR внутри приложения), access-кука — `SameSite=Lax`.

## Документация

- `docs/design-plan.md` — master-план системы (требования по модулям).
- `docs/plan-pricelist-mapping.md` — ход работ по прайс-маппингу, P1 и P2 (статусы, smoke).
- `KODA.md` — подробный контекст для контрибьюторов (архитектура, модели, конфигурация).
- `AGENTS.md` — правила разработки: структура, стиль, команды, коммиты.
