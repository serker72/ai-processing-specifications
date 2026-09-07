# Master Plan: AI-система обработки спецификаций и генерации КП (v3 - Modern Stack)

**Стек технологий:**

* **Язык и управление зависимостями:** Python 3.13, менеджер пакетов `uv` (Astral).
* **Backend:** FastAPI, SQLAlchemy 2.0 (async), Alembic, Celery (или arq) для фоновых задач.
* **База данных и кэш:** PostgreSQL 17 (с расширением `pgvector`), Redis 7. Драйвер БД — `psycopg3` (`psycopg[binary,pool]`).
* **Хранилище файлов:** MinIO (S3-совместимое).
* **AI/LLM:** OpenAI API (`text-embedding-3-small` для векторов, `gpt-4o-mini` для анализа колонок) через библиотеку `openai` или `litellm`.
* **Frontend:** Nuxt 3, Vue 3, TailwindCSS, `thumbmarkjs` (для fingerprinting).
* **Ролевая модель:** `admin` (управление каталогом поставщиков), `manager` (разбор спецификаций клиентов).

---

## Модуль 1: Инфраструктура, Окружение и База данных

### Задача 1.1: Инициализация проекта и Docker-окружение

* **Требования к AI:**
* Инициализировать проект через `uv` (`uv init`). Указать зависимости в `pyproject.toml` (FastAPI, pydantic-settings, psycopg[binary], sqlalchemy, redis, celery, openpyxl, weasyprint).
* Подготовить `docker-compose.yml`:
* БД: `image: pgvector/pgvector:pg17` (PostgreSQL 17 со встроенным pgvector).
* Redis 7 (для Celery, кэша, сессий и JWT Blacklist).
* MinIO (хранилище S3).
* Сервисы `backend` и `worker` (билдить на базе `python:3.13-slim`, устанавливать зависимости через `uv sync`).




* **DoD:** Проект запускается через `docker compose up`, `uv` быстро резолвит зависимости.

### Задача 1.2: Схема БД (SQLAlchemy 2.0)

* **Требования к AI:**
* Использовать DSN формата: `postgresql+psycopg://user:password@host:port/dbname`.
* Создать декларативные модели:
* `User`: (id, email, password_hash, role [`admin`, `manager`]).
* `CatalogItem`: (id, sku, name, unit, price, embedding `Vector(1536)`). Настроить индекс HNSW (`vector_cosine_ops`).
* `PriceListUpload`: сессии загрузки прайсов (admin_id).
* `SpecificationUpload`: сессии загрузки спецификаций (manager_id, column_mapping).
* `SpecificationRow`: строки спецификаций (raw_data, matched_item_id, match_type, status).
* `HistoricalMatch`: словарь совпадений (raw_name_hash, raw_name, catalog_item_id) для Tier-1 матчинга.




* **DoD:** Alembic миграции генерируются успешно. В первую миграцию вручную добавлен `op.execute('CREATE EXTENSION IF NOT EXISTS vector;')`.

---

## Модуль 2: Безопасность и Stateful JWT Авторизация

### Задача 2.1: Генерация JWT с привязкой к Fingerprint

* **Требования к AI:**
* Эндпоинт `POST /api/v1/auth/login`. Принимает `email`, `password` и `fingerprint` (клиентский хэш браузера от thumbmarkjs).
* Генерация `access_token` (15 мин) и `refresh_token` (7 дней). В payload вшивается хэш `fingerprint`.
* Возврат токенов клиенту **только** через заголовки `Set-Cookie` (`HttpOnly`, `Secure`, `SameSite=Lax`).



### Задача 2.2: Серверные сессии (Redis) и Blacklist

* **Требования к AI:**
* При логине сохранять `refresh_token` в Redis по ключу `session:{user_id}:{fingerprint_hash}` (TTL 7 дней).
* Эндпоинт `POST /api/v1/auth/refresh`: принимает refresh-токен из кук и `fingerprint` из тела. Проверяет подпись, совпадение fingerprint и наличие сессии в Redis.
* **Blacklist:** При логауте/рефреше `jti` старого access-токена улетает в Redis по ключу `revoked:{jti}` (с TTL = остаток жизни токена).
* `Depends` авторизации в FastAPI проверяет токены по Blacklist.


* **DoD:** Защита от угона сессии (Session Hijacking) реализована.

---

## Модуль 3: Панель Администратора (Наполнение базы)

### Задача 3.1: Загрузка прайс-листов (Превью и Маппинг)

* **Требования к AI:**
* Эндпоинт `POST /api/v1/admin/pricelists` (только для роли `admin`).
* Файл сохраняется в MinIO.
* Чтение первых 50 строк (pandas/openpyxl) -> отправка в `gpt-4o-mini` с использованием Structured Outputs.
* LLM возвращает Pydantic-схему ролей колонок (Где артикул? Где название? Где цена?).
* Возврат предложенного маппинга на фронтенд для ручного подтверждения администратором.



### Задача 3.2: Векторизация каталога (Background Worker)

* **Требования к AI:**
* Фоновая задача Celery (после подтверждения маппинга).
* Построчное чтение прайс-листа из S3.
* Батчевая генерация эмбеддингов (`text-embedding-3-small`) пачками по 500 строк.
* Эффективный UPSERT через `psycopg3` в таблицу `CatalogItem`.


* **DoD:** Большие прайсы обрабатываются асинхронно без блокировки event-loop'а.

---

## Модуль 4: Ядро поиска (Matching Engine)

### Задача 4.1: Трехуровневый алгоритм сопоставления

* **Требования к AI:**
Реализовать сервис `match_row(raw_name: str, sku: str | None)`.
1. **Tier 1 (AUTO):** Поиск по SHA-256 хэшу строки в `HistoricalMatch`. Если есть -> мгновенный O(1) возврат.
2. **Tier 2 (TOP_N):** Генерация эмбеддинга строки. SQL-запрос через SQLAlchemy в PostgreSQL 17 используя оператор `<=>`. Получение ТОП-5 вариантов, если cosine score $\ge 0.70$.
3. **Tier 3 (UNMATCHED):** Если score $< 0.70$, строка помечается как ненайденная.

### Задача 4.2: Подтверждение совпадений и пополнение Tier-1 словаря

* **Требования к AI:**
* Эндпоинт `POST /api/v1/manager/match/confirm` (доступ: `manager`).
* Принимает `raw_name`, `catalog_item_id` и `tier`.
* Сохраняет подтверждённое совпадение в таблицу `HistoricalMatch` (ключ — SHA-256 хэш `raw_name`).
* После подтверждения следующая строка с тем же наименованием будет мгновенно найдена через Tier 1 (O(1) lookup).

---

## Модуль 5: Рабочее место Менеджера (Спецификации)

### Задача 5.1: Прием файлов клиентов

* **Требования к AI:**
* Эндпоинт `POST /api/v1/manager/specifications` (Доступ: `manager`).
* Загрузка Excel, чтение превью, вызов `gpt-4o-mini` для предсказания колонок (name, quantity и т.д.).
* Сохранение конфигурации (маппинга).



### Задача 5.2: Асинхронный процессинг и Real-Time (SSE)

* **Требования к AI:**
* Celery-воркер прогоняет все строки файла клиента через Matching Engine (Модуль 4).
* Каждая обработанная строка пишется в `SpecificationRow` и публикуется в Redis Pub/Sub (`channel: spec_{id}`).
* Эндпоинт `GET /api/v1/manager/specifications/{id}/stream` (FastAPI EventSourceResponse) для передачи событий на фронтенд по мере обработки.



---

## Модуль 6: Frontend (Nuxt 3)

### Задача 6.1: Настройка API и ThumbmarkJS

* **Требования к AI:**
* Подключить `thumbmarkjs` для генерации уникального fingerprint устройства.
* Настроить `ofetch` (стандартный fetch в Nuxt) интерцепторы:
* `credentials: 'include'` (отправка кук).
* Автоматический перехват HTTP 401 -> запрос на `/api/v1/auth/refresh` -> повтор оригинального запроса.





### Задача 6.2: Интерфейсы (Admin & Manager)

* **Требования к AI:**
* Middleware защиты роутов (`/admin/*`, `/manager/*`).
* **Admin UI:** Форма загрузки прайсов, интерфейс подтверждения колонок, таблица номенклатуры (каталог).
* **Manager UI:** Рабочий стол спецификации. Таблица с виртуальным скроллом, подключенная к SSE.
* Цветовое кодирование: зеленый (Точное совпадение), желтый (ТОП-5 на выбор), красный (Не найдено).
* Действия пользователя (Выбрать из списка, Исключить, Подтвердить) записывают связи в базу `HistoricalMatch` для Tier-1.





---

## Модуль 7: Генератор Коммерческого Предложения

### Задача 7.1: Сборка и экспорт документа

* **Требования к AI:**
* Эндпоинт `GET /api/v1/manager/specifications/{id}/export?format=pdf|xlsx`.
* Джоин подтвержденных `SpecificationRow` (количество) с `CatalogItem` (цена, артикул). Расчет сумм и НДС.
* Генерация PDF (через `weasyprint` + HTML шаблон Jinja2) или XLSX (`openpyxl` с форматированием ячеек).


* **DoD:** Менеджер получает оформленный файл коммерческого предложения по клику на кнопку в UI.