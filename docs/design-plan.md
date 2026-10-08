# Master Plan: AI-система обработки спецификаций и генерации КП (v3 - Modern Stack)

**Стек технологий:**

* **Язык и управление зависимостями:** Python 3.13, менеджер пакетов `uv` (Astral).
* **Backend:** FastAPI, SQLAlchemy 2.0 (async), Alembic, Celery (или arq) для фоновых задач.
* **База данных и кэш:** PostgreSQL 17 (с расширением `pgvector`), Redis 7. Драйвер БД — `psycopg3` (`psycopg[binary,pool]`).
* **Хранилище файлов:** MinIO (S3-совместимое).
* **AI/LLM:** `litellm` как единый фасад. Эмбеддинги — локальная модель `intfloat/multilingual-e5-base` (768-dim, `EmbeddingService`); анализ колонок/предсказание маппинга — по умолчанию локальная `ollama/qwen2.5:7b`, опционально облачная `gpt-4o-mini` (`LLM_PROVIDER=openai`).
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
* `CatalogItem`: (id, sku, name, unit, price, embedding `Vector(768)`). Настроить индекс HNSW (`vector_cosine_ops`).
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
* Возврат токенов клиенту **только** через заголовки `Set-Cookie` (`HttpOnly`, `Secure`). `SameSite`: access-кука — `Lax` (короткоживущая, участвует в навигациях/SSR), refresh-кука — `Strict` (вызывается только XHR внутри приложения, кросс-сайтовых refresh нет).



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
* Чтение первых 50 строк (openpyxl) -> отправка в LLM (`litellm`: `ollama/qwen2.5:7b` по умолчанию, `gpt-4o-mini` опционально) с использованием Structured Outputs.
* LLM возвращает Pydantic-схему ролей колонок (Где артикул? Где название? Где цена?).
* Возврат предложенного маппинга на фронтенд для ручного подтверждения администратором.

* **✅ Реализация:**
  * ✅ Эндпоинт `POST /api/v1/admin/pricelists` загружает файл в MinIO и возвращает `202 Accepted` с `upload_id` без ожидания LLM.
  * ✅ Celery-таска `pricelist.predict_mapping` выполняет LLM-анализ асинхронно (в фоне).
  * ✅ Статус `mapping_processing` (в `UploadStatus`) публикуется на время анализа, по завершении — `mapping_predicted` / `failed`.
  * ✅ SSE-поток `GET /api/v1/admin/pricelists/{upload_id}/stream` — фронтенд показывает превью с маппингом после события готовности.



### Задача 3.2: Векторизация каталога (Background Worker)

* **Требования к AI:**
* Фоновая задача Celery (после подтверждения маппинга).
* Построчное чтение прайс-листа из S3.
* Батчевая генерация эмбеддингов (`intfloat/multilingual-e5-base`, 768-dim) пачками по 500 строк.
* Эффективный UPSERT через `psycopg3` в таблицу `CatalogItem`.


* **DoD:** Большие прайсы обрабатываются асинхронно без блокировки event-loop'а.

* **✅ Реализация:**
  * ✅ Celery-таска `catalog.vectorize` (`app/worker/tasks.py`): читает прайс из MinIO через `PriceListService.parse_pricelist` по подтверждённому `column_mapping`, батчи по 500 строк, эмбеддинги `EmbeddingService` (`intfloat/multilingual-e5-base`, 768-dim), UPSERT в `CatalogItem`.
* ⚠️ **Исправлено: чтение файла из MinIO только через `MinioService`.** `parse_pricelist` вызывал клиент S3 напрямую с сырым ключом, тогда как при загрузке ключ URL-кодируется (`quote`). Для имён с пробелами/кириллицей (`pricelists/…-260906 Прайс.xlsx`) `HeadObject` возвращал 404, и таска помечала загрузку `failed`. Теперь используется `MinioService.download_fileobj` (кодирует ключ). Правило: не обращаться к `_get_client()`/`_bucket` из других сервисов — только через методы `MinioService`.

* **✅ Реализовано: SSE-индикация процесса векторизации прайс-листа (без процентов) + отдельное событие завершения.**
  * `catalog.vectorize` публикует прогресс после каждого батча через `RedisPubSub.publish(..., buffered=True)`, событие содержит `processed` / `total`;
  * `PriceListProgressEvent` в `app/schemas/sse_events.py` с полями `upload_id`, `seq`, `processed`, `total`, `status` (`processing` / `completed` / `error`);
  * `total` известен после `parse_pricelist`; до этого — событие «подготовка» без чисел (`processed=total=None`);
  * **отдельное событие завершения** (`status: completed` / `error`) — публикуется последним, клиент по нему закрывает поток и обновляет данные;
  * общий счётчик `seq` (Redis INCR) на канал `pricelist_{upload_id}` — нумерация монотонна между тасками LLM-маппинга и векторизации;
  * composable `useSseStream` (общий стрим-хелпер) + `useSpecStream` (тонкая обёртка) — `frontend` сам решает, что отображать;
  * на странице `/admin/pricelists` показывается индикатор прогресса «5 000 / 75 000 записей» (подписка только на статус `processing`) + тост о завершении/ошибке.

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
* Загрузка Excel, чтение превью, вызов LLM (`litellm`) для предсказания колонок (name, quantity и т.д.).
* Сохранение конфигурации (маппинга).
* **Реализация:**
  * ✅ Эндпоинт `POST /api/v1/manager/specifications` (manager role).
  * ✅ `SpecificationRepository` — CRUD для `SpecificationUpload` и `SpecificationRow`.
  * ✅ `SpecificationService` — потоковая загрузка в MinIO, превью 50 строк, LLM-предсказание маппинга.
  * ✅ `SpecificationMappingPrediction` — Pydantic-схема ответа LLM (name, quantity, unit, price, additional_columns).
  * ✅ DI-провайдеры для `SpecificationRepository` и `SpecificationService`.
  * ✅ Smoke-тест: загрузка Excel → MinIO + превью + LLM-маппинг → 201 Created.

* **✅ Реализовано: LLM-маппинг вынесен из HTTP-запроса в фоновую задачу (по образцу Задачи 3.1).**
  * `POST /api/v1/manager/specifications` выполняет только быструю часть
    (`SpecificationService.create_upload`: проверка размера/клиента + файл в MinIO +
    запись `pending`) и сразу возвращает `202 Accepted` с `upload_id`;
  * Celery-таска `specification.predict_mapping` (`app/worker/tasks.py`) — превью
    50 строк из MinIO + LLM-предсказание маппинга (`SpecificationService.predict_mapping`);
  * статусы: `pending → mapping_processing → mapping_predicted | failed`
    (`UploadStatus.mapping_processing`);
  * после успеха таска матчинга ставится из сервиса (`process_specification.delay`) —
    маппинг спецификаций не подтверждается вручную, в отличие от прайс-листов;
  * события `SpecificationStatusEvent` (`app/schemas/sse_events.py`) публикуются в тот же
    канал `spec_{upload_id}`, что и прогресс матчинга; `seq` — общий счётчик канала
    (Redis INCR, `RedisPubSub.next_seq`), клиент получает полный цикл одним потоком;
  * frontend: подпись статуса `mapping_processing` и поллинг списка, пока статусы
    `pending / mapping_processing / processing` (`manager/uploads.vue`).

* **✅ Реализовано: защита от гонки «векторизация каталога ↔ матчинг спецификации».**
  Выбранное решение (простейшее): **при `POST /api/v1/manager/specifications` проверять,
  нет ли загрузок прайс-листов в статусе `processing`, и при наличии возвращать `409`
  с сообщением «идёт обновление каталога, попробуйте позже».**
  * `SpecificationService.is_catalog_updating()` — по
    `PriceListRepository.count_by_status()` / фильтру `processing`;
  * текст ошибки — `SpecificationMessages.CATALOG_UPDATING` (не хардкод);
  * frontend — `toast.fromError` показывает `detail` ответа 409 на
    `manager/specifications/index.vue`;
  * не покрывает узкое окно (векторизация стартовала после начала матчинга); для строгой
    корректности потребовалась бы двусторонняя блокировка с TTL — не делаем.

---

### Задача 5.2: Асинхронный процессинг и Real-Time (SSE)

* **Требования к AI:**
* Celery-воркер прогоняет все строки файла клиента через Matching Engine (Модуль 4).
* Каждая обработанная строка пишется в `SpecificationRow` и публикуется в Redis Pub/Sub (`channel: spec_{id}`).
* Эндпоинт `GET /api/v1/manager/specifications/{id}/stream` (FastAPI EventSourceResponse) для передачи событий на фронтенд по мере обработки.

* **✅ Реализация:**
  * ✅ Celery-таска `specification.process` (`app/worker/tasks.py`): читает Excel из MinIO по `column_mapping`, батчи по 100 строк, результат в `SpecificationRow`.
  * ✅ `app/worker/redis_pubsub.py` — публикация в канал `spec_{upload_id}`; схемы событий `app/schemas/sse_events.py` (`RowMatchEvent`, `ProgressEvent`).
  * ✅ `GET /api/v1/manager/specifications/{upload_id}/stream` — `StreamingResponse` (`text/event-stream`) с подпиской на Redis Pub/Sub, отписка по disconnect клиента.
  * ✅ `POST /api/v1/manager/specifications` запускает таску (`process_specification.delay`) после сохранения upload.
  * ✅ `RowStatus.processing` / `RowStatus.unmatched` — промежуточные состояния обработки.
  * ⚠️ Вместо `sse_starlette.EventSourceResponse` — `StreamingResponse`: формат `data: …\n\n` отдаётся напрямую, лишняя зависимость не нужна.



---

## Модуль 6: Frontend (Nuxt 3)

### Задача 6.1: Настройка API и ThumbmarkJS

* **Требования к AI:**
* Подключить `thumbmarkjs` для генерации уникального fingerprint устройства.
* Настроить `ofetch` (стандартный fetch в Nuxt) интерцепторы:
* `credentials: 'include'` (отправка кук).
* Автоматический перехват HTTP 401 -> запрос на `/api/v1/auth/refresh` -> повтор оригинального запроса.

* **✅ Реализация:**
* `app/plugins/thumbmark.client.ts` — client-only плагин ThumbmarkJS: отпечаток генерируется один раз, кладётся в `useState` и `localStorage`, прогревается в фоне.
* `app/plugins/api.ts` — `$api` (`$fetch.create`): `credentials: 'include'`, `retry: 0`, `Content-Type` не задаётся явно (иначе ломается multipart-загрузка).
* Интерцептор `onResponseError`: на 401 (кроме auth-эндпоинтов) вызывает `/auth/refresh` «чистым» клиентом без интерцептора и повторяет исходный запрос. Рефреш один на волну 401 — параллельные запросы страницы ждут общий `Promise`, а не обновляют токен каждый сам. Если рефреш не помог, состояние пользователя очищается и выполняется переход на `/login?redirect=…`.
* Все страницы ходят через `$api` (в `useState`-композаблах и на страницах); исключение — `EventSource` для SSE, где заголовок/клиент задать нельзя.
* ⚠️ `useAuth().refresh()` остаётся явным (его вызывает `ensureAuth()` из guard'а); интерцептор обновляет токен своим запросом, чтобы не создавать рекурсию `$api → refresh → $api`.





### Задача 6.2: Интерфейсы (Admin & Manager)

* **Требования к AI:**
* Middleware защиты роутов (`/admin/*`, `/manager/*`).
* **Admin UI:**
  * **Управление пользователями:** Таблица пользователей с фильтрацией по роли, редактирование прав.
  * **Управление устройствами:** Список зарегистрированных fingerprint-устройств, возможность блокировки.
  * **Управление сессиями:** Активные сессии пользователей, функция принудительного выхода (отзыв сессии).
  * Форма загрузки прайс-листов, интерфейс подтверждения колонок, таблица номенклатуры (каталог).
* **Manager UI:**
  * Рабочий стол спецификации. Таблица строк с пагинацией, подключенная к SSE.
  * Цветовое кодирование: зеленый (Точное совпадение), желтый (ТОП-5 на выбор), красный (Не найдено).
  * Действия пользователя (Выбрать из списка, Исключить, Подтвердить) записывают связи в базу `HistoricalMatch` для Tier-1.
  * ⚠️ **Отклонение от исходного плана: виртуальный скролл заменён серверной пагинацией.**
    Причина: `GET /api/v1/manager/specifications/{id}/rows` уже отдаёт строки страницами
    (`{rows, total, page, page_size}`); строки реактивно меняются во время SSE-обработки
    (`processing` → `matched`/`unmatched`) и при действиях менеджера, а при виртуализации
    пришлось бы согласовывать вставки/обновления в списке — сложнее и рискованнее. При
    спецификациях по 50 строк на страницу выигрыш виртуализации (тысячи DOM-узлов) не
    проявляется. Фактическая реализация — `app/pages/manager/specifications/[uploadId].vue`
    (пагинация по 50 строк).

* **✅ Реализация:**
* **Общий Layout** (`app/layouts/workspace.vue`): единый Sidebar для администратора и менеджера + кнопка выхода; наполнение меню по роли — `app/composables/useNavMenu.ts`. Домашний маршрут роли (`useAuth.ROLE_HOME`) берётся из первого пункта `ROLE_NAV`, поэтому меню и редирект после входа не могут разойтись. Заглушка `pages/dashboard.vue` удалена.
* **Backend админки** (`app/api/v1/admin_access.py` + `admin.py`, авторизация через `get_current_admin`):
  * `GET /api/v1/admin/users`, `PATCH /api/v1/admin/users/{id}` — список и смена роли (`UserService`; сменить собственную роль нельзя — 400).
  * `GET /api/v1/admin/devices`, `PATCH /api/v1/admin/devices/{fp_hash}` — реестр устройств и блокировка (`DeviceService`); блокировка дополнительно отзывает активные сессии отпечатка.
  * `GET /api/v1/admin/sessions`, `DELETE /api/v1/admin/sessions/{user_id}/{fp_hash}` — сессии из Redis (`SCAN session:*`) и отзыв с занесением jti refresh-токена в blacklist (`SessionAdminService`).
  * `GET /api/v1/admin/pricelists` — история загрузок прайс-листов; `GET /api/v1/admin/catalog?page&page_size&search` — позиции номенклатуры страницами с поиском.
* **Модель `Device`** (`app/models/models.py`, миграция `c9cc1eb10b21`): `fingerprint_hash` (SHA-256, unique), `blocked`, `first_seen_at`, `last_seen_at`. Регистрация — upsert в `AuthService.login` (`DeviceRepository.touch`), вход с заблокированного устройства — 403 (`AuthMessages.DEVICE_BLOCKED`). Хранится только хэш отпечатка.
* **Users** (`app/pages/admin/users.vue`): таблица пользователей из `/admin/users`, выбор роли → PATCH; своя строка заблокирована на клиенте так же, как на backend.
* **Devices** (`app/pages/admin/devices.vue`): список устройств (хэш сокращён, полный — в `title`), блокировка/разблокировка PATCH-запросом.
* **Sessions** (`app/pages/admin/sessions.vue`): активные сессии (email пользователя, отпечаток, срок истечения refresh-токена), отзыв DELETE-запросом.
* **Pricelists** (`app/pages/admin/pricelists/index.vue`): загрузка Excel (multipart через `$api`) + история загрузок со статусами обработки, фильтр-чипы по статусу и пагинация.
* **Catalog** (`app/pages/admin/catalog.vue`): таблица номенклатуры с поиском и пагинацией.
* **Шаблоны КП** (`app/pages/admin/proposal-templates.vue`): загрузка, правка названия/даты (PATCH) и удаление; ошибки показываются на странице, а не `alert`/`console`.
* **Manager** (`app/pages/manager/specifications/index.vue`): загрузка спецификаций + SSE-лог обработки; рабочий стол строк — `app/pages/manager/specifications/[uploadId].vue`.
* **Middleware** (`app/middleware/auth-guard.global.ts`): глобальный, защищает роуты `/admin/*` и `/manager/*` по роли из `/auth/me`. Работает на клиенте (куки ставит backend на своём origin, SSR их не видит) — настоящий контроль ролей остаётся на backend (`require_role`).
* **Smoke-тест:** сборка Nuxt — 2.16 MB (548 kB gzip), все роуты доступны; эндпоинты: admin — 200, manager на `/admin/*` — 403, гость — 401; блокировка устройства → вход с него 403, после разблокировки — 204; отзыв сессии уменьшает список и повторяет 404.
* **Осталось в рамках задачи:** ничего критичного; см. примечание об отклонении
  (виртуальный скролл → пагинация). Фильтрация пользователей по роли в UI не реализована —
  таблица `app/pages/admin/users.vue` показывает всех пользователей со сменой роли. Прочее
  из ранее перечисленного закрыто: редактирование каталога (P2.2), интерфейс подтверждения
  колонок прайс-листа (P0), действия менеджера над строками (P1).


### Задача 6.3: Добавить TailwindCSS и темы

* **Требования к AI:**
* Подключить TailwindCSS v4 в Nuxt 3 через `@tailwindcss/vite` (без `tailwind.config.js` — конфигурация на уровне CSS).
* Единая точка стилей `app/assets/css/main.css`: `@import "tailwindcss"` + токены темы в CSS-переменных (`--app-bg`, `--app-surface`, `--app-border`, `--app-text`, `--app-muted`, `--app-accent`).
* **Темы (light/dark):** переключение классом `.dark` на `<html>`, а не только системной настройкой — переопределить вариант через `@custom-variant dark (&:where(.dark, .dark *))`.
* Выбор пользователя хранить в `localStorage` (ключ `app_theme`), по умолчанию — `prefers-color-scheme`.
* Инлайновый блокирующий скрипт в `<head>` должен применять тему до гидратации (иначе FOUC между SSR и клиентом), плюс синхронизировать `style.colorScheme`.
* Компонент переключателя темы (`ThemeToggle`) в шапке/сайдбаре; существующие страницы Admin/Manager перевести на токены темы (никаких хардкод-цветов в разметке).
* **DoD:** Светлая и тёмная темы работают без мигания при перезагрузке, сборка Nuxt проходит успешно.

* **✅ Реализация:**
* **Зависимости** (`frontend/package.json`): `tailwindcss@^4.3`, `@tailwindcss/vite@^4.3`.
* **Конфигурация** (`frontend/nuxt.config.ts`): плагин `tailwindcss()` в `vite.plugins`, `css: ['~/assets/css/main.css']`, блокирующий скрипт темы в `app.head.script` (`tagPosition: 'head'`).
* **Стили** (`app/assets/css/main.css`): `@import "tailwindcss"`, `@custom-variant dark`, токены `:root` / `html.dark`, базовые классы компонентов (`card`, формы, таблицы, бейджи статусов).
* **Composable** (`app/composables/useTheme.ts`): чтение/запись `app_theme`, резолв по `prefers-color-scheme`, `toggleTheme()`, реакция на смену системной темы.
* **Компонент** (`app/components/common/ThemeToggle.vue`): кнопка переключения light/dark.
* **Токены в утилитах Tailwind** (`@theme inline` в `main.css`): `--color-app-*: var(--app-*)` — классы `bg-app-surface`/`text-app-muted` читают ту же переменную, что и базовые стили, дублирования палитры нет.
* **Контраст:** сплошные кнопки используют `--app-on-accent` (белый в светлой теме, тёмный в тёмной); пары фон/текст проверены по формуле WCAG — ≥ 4.5:1 в обеих темах.





---

## Модуль 7: Генератор Коммерческого Предложения

### Задача 7.1: Загрузка шаблонов Коммерческого Предложения

* **Требования к AI:**
* Модель `ProposalTemplate` (БД): `name`, `html_key` (ключ файла в MinIO), `start_date` (DATE, обязательно).
* Эндпоинты:
  * `POST /api/v1/admin/proposal-templates` — загрузка HTML-шаблона в MinIO + создание записи.
  * `GET /api/v1/admin/proposal-templates` — список шаблонов (сортировка по `start_date DESC`).
  * `PATCH /api/v1/admin/proposal-templates/{id}` — обновление названия и даты.
  * `DELETE /api/v1/admin/proposal-templates/{id}` — удаление шаблона и файла из MinIO.
* Валидация при создании:
  * `start_date` обязателен (нельзя создать без даты).
  * `start_date > today` (дата начала должна быть в будущем).
  * `start_date > max(start_date)` из существующих шаблонов (новая дата позже любой существующей).
* Определение текущего шаблона: ближайший `start_date >= CURRENT_DATE`.
* Frontend: страница `/admin/proposal-templates` с формой загрузки (HTML-файл, название, date picker) и таблицей шаблонов.

* **✅ Реализация:**
  * ✅ Модель `ProposalTemplate` (`app/models/models.py`) + миграция `proposal_templates`; уникальный индекс по `start_date` — иначе «текущий шаблон» неоднозначен.
  * ✅ `ProposalTemplateRepository` (create/get_by_id/list_all/get_max_start_date/get_current_template/update/delete) и `ProposalTemplateService` с валидацией дат в UTC.
  * ✅ `POST`/`GET` `/api/v1/admin/proposal-templates`, `PATCH`/`DELETE /api/v1/admin/proposal-templates/{id}` (multipart: `file`, `name`, `start_date`; проверка расширения `.html`).
  * ✅ DI-провайдеры репозитория и сервиса; `MinioService.download_fileobj` для чтения HTML.
  * ✅ Страница `/admin/proposal-templates`: форма загрузки, таблица, удаление, подсветка действующего шаблона, инлайн-редактирование названия/даты (PATCH).

### Задача 7.2: Сборка и экспорт документа

* **Требования к AI:**
* Эндпоинт экспорта КП (только PDF).
* Джоин подтвержденных `SpecificationRow` (количество) с `CatalogItem` (цена, артикул). Расчет сумм и НДС.
* Генерация PDF (через `weasyprint` + HTML шаблон Jinja2), сохранение в MinIO, скачивание в браузере пользователя.

* **✅ Реализация:**
  * ✅ Backend: `ProposalService` + `proposals`/`proposal_documents`/`proposal_counters` (миграция `f4d5e6a7b8c9`); состав КП — строки `confirmed`/`matched`; цена из `CatalogItem`; НДС из системных настроек; `rows_fingerprint` для контроля устаревания; нумерация `КП-{год}-{5 цифр}`.
  * ✅ Эндпоинты (фактические, вместо `.../export?format=...`): `GET/POST /api/v1/manager/specifications/{upload_id}/proposal` (текущее состояние / формирование, `force`), `GET /api/v1/manager/proposals` (история менеджера), `GET /api/v1/manager/proposals/{proposal_id}/download` (PDF из MinIO).
  * ✅ Frontend: панель формирования/скачивания на рабочем столе (`manager/specifications/[uploadId].vue`) и страница истории `/manager/proposals`.
  * ⚠️ **XLSX не реализован** (только PDF); параметра `format` нет.

* **DoD:** Менеджер получает оформленный файл коммерческого предложения по клику на кнопку в UI. ✅ Выполнено (PDF).

---

## Обнаруженные проблемы (smoke обработки прайс-листа, 2026-10-08)

Зафиксировано при тестовом прогоне: удалены 200 случайных записей из `catalog_items`
(74 924 → 74 724), загружен тестовый прайс, выполнено подтверждение маппинга и
векторизация каталога.

1. **`RuntimeError: Event loop is closed` в логах worker перед вызовом LLM для маппинга.**
   * **Причина:** фоновая задача логирования `litellm.LoggingWorker._worker_loop`
     (`litellm/litellm_core_utils/logging_worker.py:122`, litellm 1.97.0) переживает
     закрытие event loop Celery-таски. Таска создаёт собственный loop
     (`asyncio.new_event_loop()` в `app/worker/tasks.py`) и закрывает его после
     `run_until_complete`, а глобальный `GLOBAL_LOGGING_WORKER` остаётся привязан к
     закрытому loop.
   * **Влияние:** только шум в логах (`Task was destroyed but it is pending!`), на
     выполнение задачи не влияет — `specification.predict_mapping` завершается успешно.
   * **Статус:** требуется исправление (остановка/сброс `GLOBAL_LOGGING_WORKER` перед
     закрытием loop либо переиспользование одного loop на процесс воркера).

2. **401 при подтверждении маппинга прайса — экран не обновляется после `/auth/refresh`.**
   * **Сценарий:** `POST /admin/pricelists/{id}/confirm` → 401 → frontend
     `/auth/refresh` → повтор запроса → обработка строк прайса уже запущена, но UI
     остаётся на форме подтверждения маппинга с активной кнопкой confirm.
   * **Причина:** после успешного повторного запроса страница не перечитывает статус
     загрузки и не переходит в режим обработки; кнопка не блокируется и не реагирует на
     смену статуса.
   * **Статус:** требуется исследование `frontend/app/pages/admin/pricelists/[uploadId].vue`
     (обработчик confirm + реакция на статус).

3. **Неоптимальная векторизация каталога: эмбеддинги пересчитываются для всех строк.**
   * После изменения 200 записей `catalog.vectorize` заново считает эмбеддинги для
     всех ~74 924 строк.
   * **Предложение:** добавить колонку с хэшем `sku + name` (`content_hash`); при
     векторизации пропускать строки с неизменившимся хэшем, пересчитывать эмбеддинг
     только для новых/изменённых позиций.
   * **Статус:** требуется миграция + изменение `catalog.vectorize`/UPSERT.

4. **Поллинг списков вместо подписки на SSE (на `/admin/pricelists` и в кабинете менеджера).**
   * **Незакрытая задача из `docs/plan-pricelist-mapping.md`** — раздел
     «Требуется доработка: индикация и события обработки прайса (2026-10-03)», **пункт 2
     «Заменить polling на события»**. Пункт 1 той же секции (индикация векторизации)
     закрыт, пункт 2 — нет.
   * В консоли браузера циклически идут `GET /admin/pricelists?page=1&page_size=20`,
     хотя по плану от поллинга должны были отказаться в пользу SSE.
   * **Причина:** поллинг — это механизм из **P2.6** («Авто-обновление статусов»,
     коммит `d20dc29`), а не осознанно оставленный фолбэк под SSE. Задача «Заменить
     polling на события» была зафиксирована в `docs/plan-pricelist-mapping.md`
     (2026-10-03), но выполнена лишь частично: SSE-потоки сделали, а поллинг на
     страницах-списках не убрали.
   * Страница списка `/admin/pricelists` держит поллинг каждые 5 с
     (`frontend/app/pages/admin/pricelists/index.vue`, строки 154, 242–250, 356–366):
     `setInterval(pollProcessing, 5000)`. Запрос уходит, пока глобальные счётчики
     `counts.processing`/`counts.mapping_processing` > 0 (или на текущей странице есть
     загрузка в этих статусах). Поскольку векторизация каталога идёт долго (см.
     проблему 3 — пересчёт 74 924 эмбеддингов), счётчик `processing` остаётся > 0 и
     поллинг не прекращается.
   * **Тот же паттерн в других местах (исследование):**
     * `frontend/app/pages/manager/uploads.vue` (строки 102–103, 137–143, 158–168) —
       `setInterval(pollProcessing, 5000)`, опрос `GET /manager/specifications`.
     * `frontend/app/pages/manager/specifications/[uploadId].vue` (строки ~485–499) —
       `setInterval(pollProcessing, 5000)`, опрос деталей и строк спецификации.
     * `frontend/app/pages/admin/pricelists/[uploadId].vue` — поллинга нет, только SSE
       с backoff (корректный образец).
   * SSE-потоки уже существуют и публикуют те же статусы
     (`pricelist_{upload_id}` и `spec_{upload_id}`, буфер в Redis + дедупликация по `seq`),
     поэтому поллинг избыточен.
   * **Статус:** требуется замена/удаление поллинга на страницах списков (переход на
     SSE-события статусов; поллинг оставить максимум как редкий страховочный фолбэк).

5. **Неудобная пагинация и отсутствие сортировки в таблицах.**
   * Пагинация только «вперёд/назад»; нет перехода на первую/последнюю/указанную
     страницу, нет выбора размера страницы.
   * Нет сортировки по колонкам таблицы.
   * **Исследование (что есть сейчас):**
     * `frontend/app/pages/admin/pricelists/index.vue` (строки 104–120) — только
       «← Назад» / «Вперёд →», фиксированный `PAGE_SIZE = 20`. Backend
       `GET /admin/pricelists` (`backend/app/api/v1/admin.py:182`) принимает только
       `page`, `page_size`, `status`; сортировка жёстко `created_at DESC`
       (`price_list_repository.list_filtered`).
     * `frontend/app/pages/admin/catalog.vue` (строки 90–104) — только «Назад» /
       «Вперёд», фиксированный `PAGE_SIZE = 50`. Backend `GET /admin/catalog`
       (`admin.py:328`) принимает `page`, `page_size`, `search`; сортировка жёстко
       `name ASC` (`catalog_repository.list_items`).
     * `frontend/app/pages/manager/specifications/[uploadId].vue` (строки 140–160) —
       только «← Назад» / «Вперёд →». Backend `GET .../rows`
       (`manager.py:236`) принимает `page`, `page_size`, `status`; сортировка жёстко
       `row_number ASC` (`specification_repository.list_rows`).
     * `frontend/app/pages/manager/uploads.vue` — пагинации нет вовсе: backend
       `GET /manager/specifications` (`manager.py:175`) отдаёт весь список менеджера
       (`list_by_manager`, `created_at DESC`) без `page`/`page_size`.
   * **Ни один backend-эндпоинт не принимает параметр сортировки** — для сортировки по
     колонкам потребуется добавить `sort_by`/`sort_order` в API и репозитории.
   * **Статус:** требуется доработка backend (сортировка, при необходимости — пагинация
     списка спецификаций менеджера) и frontend (компонент пагинации с переходом на
     первую/последнюю/указанную страницу + клики по заголовкам колонок).
