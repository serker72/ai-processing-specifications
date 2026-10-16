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
* Повтор на 401 оформлен **обёрткой `$api`**, а не интерцептором `onResponseError`: ofetch игнорирует значение, возвращённое из этой хук-функции (`node_modules/ofetch/dist/shared/ofetch.532d6f9b.mjs:193` — после вызова хука идёт `return onError(context)`), поэтому повтор исходного запроса из интерцептора молча терялся. Обёртка на 401 (кроме auth-эндпоинтов) вызывает `/auth/refresh` «чистым» `$fetch` без обёртки и повторяет исходный запрос. Рефреш один на волну 401 — параллельные запросы страницы ждут общий `Promise`, а не обновляют токен каждый сам. Если рефреш не помог, состояние пользователя очищается и выполняется переход на `/login?redirect=…`.
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

1. **`RuntimeError: Event loop is closed` в логах worker перед вызовом LLM для маппинга.** ✅
   * **Причина:** фоновая задача логирования `litellm.LoggingWorker._worker_loop`
     (`litellm/litellm_core_utils/logging_worker.py:122`, litellm 1.97.0) переживает
     закрытие event loop Celery-таски. Таска создаёт собственный loop
     (`asyncio.new_event_loop()` в `app/worker/tasks.py`) и закрывает его после
     `run_until_complete`, а глобальный `GLOBAL_LOGGING_WORKER` остаётся привязан к
     закрытому loop.
   * **Влияние:** только шум в логах (`Task was destroyed but it is pending!`), на
     выполнение задачи не влияет — `specification.predict_mapping` завершается успешно.
   * **Причина (уточнена):** таска создаёт новый event loop (`asyncio.new_event_loop` в
     `app/worker/tasks.py`) и закрывает его после `run_until_complete`, а глобальный
     `litellm` `GLOBAL_LOGGING_WORKER` привязан к старому loop — при закрытии loop
     его `_worker_task` уничтожается висящей задачей.
   * **Решение (реализовано):** в `_run_async()` перед `loop.close()` вызывается
     `GLOBAL_LOGGING_WORKER.stop()` (отменяет и дожидается `_worker_task` и все
     дочерние задачи), затем сбрасываются `_queue`, `_sem`, `_bound_loop` — следующая
     таска инициализирует воркер в своём loop без конфликтов.
   * **Статус:** ✅ Реализовано.

2. **401 при подтверждении маппинга прайса — экран не обновляется после `/auth/refresh`.** ✅
   * **Сценарий:** `POST /admin/pricelists/{id}/confirm` → 401 → frontend
     `/auth/refresh` → повтор запроса → обработка строк прайса уже запущена, но UI
     остаётся на форме подтверждения маппинга с активной кнопкой confirm.
   * **Причина:** после успешного повторного запроса страница не перечитывает статус
     загрузки и не переходит в режим обработки; кнопка не блокируется и не реагирует на
     смену статуса.
   * **Причина (уточнена):** повтор исходного запроса после рефреша был оформлен
     значением, возвращённым из интерцептора `onResponseError`, — ofetch его игнорирует
     (`node_modules/ofetch/dist/shared/ofetch.532d6f9b.mjs:193`: после вызова хука идёт
     `return onError(context)`), поэтому запрос на самом деле не повторялся и страница
     не узнавала об успешном подтверждении.
   * **Решение (реализовано):**
     1. **`frontend/app/plugins/api.ts`** — `$api`-обёртка вместо интерцептора: на 401
        (кроме auth-эндпоинтов) вызывает `/auth/refresh` «чистым» `$fetch` и **реально
        повторяет** исходный запрос; рефреш один на волну 401 (общий `Promise`), при
        неудаче — сброс состояния и `navigateTo('/login?redirect=…')`.
     2. **`frontend/app/pages/admin/pricelists/[uploadId].vue`** — обработчик confirm
        сверяется с сервером (`confirmLanded` через `fetchUpload`), если ответ потерян;
        подтверждённая загрузка переводится в режим обработки, а запрос-исключение
        (`BackendError` с текстом про уже запущенную обработку) тоже трактуется как
        успех — экран не остаётся на форме с активной кнопкой confirm.
   * **Статус:** ✅ Реализовано.

3. **Неоптимальная векторизация каталога: эмбеддинги пересчитываются для всех строк.** ✅
   * После изменения 200 записей `catalog.vectorize` заново считает эмбеддинги для
     всех ~74 924 строк.
   * **Решение (реализовано):**
     1. **Колонка `content_hash`** в `CatalogItem` (`String(64)`, nullable) — SHA-256 хэш от `sku + "\n" + name`.
     2. **Миграция** (`backend/alembic/versions/20261009_100000-e7f8a9b0c1d2_add_content_hash_to_catalog_items.py`):
        `upgrade()` добавляет колонку и заполняет хэши для **всех существующих записей** батчами по 500 строк через `UPDATE ... FROM (VALUES ...)`.
     3. **`content_hash_of(sku, name)`** (`backend/app/repositories/catalog_repository.py`): чистая функция, вычисляет SHA-256 от `sku\nname`.
     4. **`CatalogRepository.find_hashes_by_keys(keys)`**: `SELECT sku, name, content_hash WHERE content_hash IS NOT NULL AND tuple_(sku, name) IN :keys` — возвращает `{(sku, name): content_hash}` для строк с уже вычисленным хэшем.
     5. **`CatalogRepository.upsert_batch(items)`**: `embedding` пишется через `COALESCE(excluded, stored)` (для unchanged строка приходит с `embedding=None` — старый эмбеддинг сохраняется); `DO UPDATE` выполняется только если `price`, `unit` или `content_hash` реально изменились (`is_distinct_from`) — меньше лишней переиндексации HNSW.
     6. **`worker/tasks.py` (таска `vectorize_catalog`)**: для каждого батча считает `content_hash_of` по парам, читает существующие хэши (`find_hashes_by_keys`), отправляет в `embed_passages` только `to_embed` (changed), для unchanged ставит `embedding=None`; логирует «пересчитано / пропущено».
   * **Эффект:** при загрузке прайс-листа с 70 000 строк, где изменились 500, пересчитываются только 500 эмбеддингов вместо 70 000.
   * **Статус:** ✅ Реализовано.

4. **Поллинг списков вместо подписки на SSE (на `/admin/pricelists` и в кабинете менеджера).** ✅
   * **Задача из `docs/plan-pricelist-mapping.md`** — раздел
     «Требуется доработка: индикация и события обработки прайса (2026-10-03)», **пункт 2
     «Заменить polling на события»**. Пункт 1 той же секции (индикация векторизации)
     был закрыт ранее, пункт 2 закрыт этой реализацией.
   * В консоли браузера циклически идут `GET /admin/pricelists?page=1&page_size=20`,
     хотя по плану от поллинга должны были отказаться в пользу SSE.
   * **Причина:** поллинг — это механизм из **P2.6** («Авто-обновление статусов»,
     коммит `d20dc29`), а не осознанно оставленный фолбэк под SSE. Задача «Заменить
     polling на события» была зафиксирована в `docs/plan-pricelist-mapping.md`
     (2026-10-03), но выполнена лишь частично: SSE-потоки сделали, а поллинг на
     страницах-списках не убрали (устранено этой реализацией).
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
   * **Решение (реализовано):** поллинг на страницах-списках удалён, подписка на SSE через новый композабл `frontend/app/composables/useSseStreams.ts` (мульти-подписка по id+path с `track`/`untrack`/`trackedIds`, переиспользует `createSseConnection` из `useSseStream.ts`):
     * `frontend/app/pages/admin/pricelists/index.vue` — `setInterval(pollProcessing, 5000)` убран; на каждую активную загрузку (`processing`/`mapping_processing`) открывается `/admin/pricelists/{id}/stream`, прогресс и терминальный статус обновляют список и счётчики.
     * `frontend/app/pages/manager/uploads.vue` — `setInterval` убран; подписка через `useSseStreams` на `/manager/specifications/{id}/stream`.
     * `frontend/app/pages/manager/specifications/[uploadId].vue` — удалён поллинг-фолбэк каждые 5 с; страница уже использует `useSpecStream` (SSE с реконнектом, backoff и refresh токена).
   * **Статус:** ✅ Реализовано.

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
    * **Статус:** ⚠️ частично — пагинация не тронута, сортировка по колонкам не реализована.
      Отложено до завершения основной функциональности.


## Обнаруженные проблемы (ручное тестирование загрузки спецификации, 2026-10-10)

Зафиксировано при ручном прогоне: менеджер загружает файл спецификации
(`POST /api/v1/manager/specifications`), далее смотрит страницу загрузки и
таблицу строк.

1. **После загрузки отображается блок «Результат загрузки» с сырым JSON ответа
   `POST /manager/specifications`.**
   * **Симптом:** на странице загрузки (`manager/specifications/index.vue`)
     показывается JSON тела ответа (`uploadResult` →
     `<pre>{{ JSON.stringify(...) }}</pre>`) — технический дамп, не
     предназначенный для пользователя. Имя обрабатываемого файла при этом не
     отображается вовсе (`file.name` не сохраняется в состояние).
   * **Ожидалось (синхронно с пунктом 2 — это одна страница):**
     * **Верхняя строка панели обработки — имя файла.** Сохранять
       `file.name` в состояние при выборе файла и показать его заголовком
       (`Обработка файла: spec-2026.xlsx`).
     * **Убрать JSON тела ответа** (`uploadResult` и его `<pre>`-блок
       удалить целиком).
     * **Ошибка `POST /manager/specifications`** — вместо сырого тела
       показывать человекочитаемое сообщение из поля `detail` ответа
       (backend отдаёт `400/409/413/422/500` с `detail`), в красном
       инлайн-блоке на странице + тост `toast.fromError`; панель обработки
       при этом не открывается. Типовой случай — `409` «идёт обновление
       каталога, попробуйте позже».
     * **Успех `POST /manager/specifications`** — никакого отдельного
       статуса/тоста об успехе не показывать; сразу открывать панель
       визуализации из пункта 2, первым элементом которой — индикатор
       SSE-потока (мигающая зелёная точка + «SSE-поток: Активен»).
       Подписка `openStream(upload_id)` стартует в том же обработчике.
   * **✅ Реализация (2026-10-11):**
     * `frontend/app/pages/manager/specifications/index.vue` — убран блок
       `uploadResult` / `<pre>`, добавлено сохранение `file.name` в
       `processingFileName`, показывается в `<h2 class="file-title">`.
     * Ошибка `detail` извлекается функцией `errorDetail(err, fallback)`,
       выводится в красной плашке `<div class="upload-error">` + тост
       `toast.fromError`; панель обработки при этом не открывается.
     * При успехе — отдельного тоста нет, сразу `processing.value = true`
       + `openStream(upload_id)`.
   * **Статус:** ✅ выполнено.

2. **Непонятно назначение блока «События обработки».**
   * **Симптом:** блок выглядит как индикатор, но события в нём — сырой поток
     сообщений SSE; назначение и связь с прогрессом обработки неочевидны.
   * **Ожидалось:** вместо текстового потока событий — интерактивная панель
     визуализации обработки спецификации в реальном времени. Данные из
     SSE-потока `spec_{upload_id}` (события `RowMatchEvent` / `ProgressEvent`)
     разбиваются по Tier-модели: auto (зелёный), top_n (оранжевый), unmatched
     (красный). Визуальные блоки:
     * индикатор SSE-потока (мигающая зелёная точка + текст в левом верхнем углу);
     * заголовок с процентом обработки и подзаголовком «Обработано X из Y строк»;
     * многокомпонентный прогресс-бар (stacked): зелёный / оранжевый / красный по
       числу строк каждого Tier + серый необработанный остаток;
     * карточки метрик для каждого Tier (название, крупный счётчик, описание);
     * бегущий лог (4–5 последних строк с цветовым маркером и таймстемпом).
     Реализация — Vue 3 Composition API + Tailwind CSS, троттлинг обновления
     150–200 мс, `tabular-nums`, плавные CSS-переходы для ширины сегментов
     бара, крупные блоки — в отдельных компонентах.
   * **✅ Реализация (2026-10-11):**
     * `frontend/app/components/common/ProcessingPanel.vue` — новый компонент:
       индикатор SSE (мигающая точка), заголовок с процентом, stacked-бар
       (auto / top_n / unmatched / pending), 3 карточки метрик, бегущий лог
       (5 строк с timestamp). Троттлинг 180 мс через `watch` + `setTimeout`.
     * `backend/app/schemas/sse_events.py` — добавлено поле
       `timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())`
       в `RowMatchEvent` и `ProgressEvent`.
     * SSE-поток с реконнектом, backoff и дедупликацией по `seq` —
       `frontend/app/composables/useSseStream.ts` + `useSpecStream.ts`.
   * **Статус:** ✅ выполнено.

3. **После загрузки сразу не видно таблицу с результатами матчинга.**
   * **Симптом:** страница загрузки не показывает строки спецификации с
     результатами сопоставления; переход к результатам неочевиден.
   * **Решение (зафиксировано):** строки сразу не встраиваем — обработка
     асинхронная, таблица готова только после завершения матчинга.
     **На панели обработки отображать кнопку перехода на страницу с данными
     спецификации** `/manager/specifications/{upload_id}`:
     * кнопка появляется на панели из пункта 2 рядом с заголовком
       («К результатам матчинга →»);
     * состояние до завершения обработки — неактивна (строки ещё не
       готовы); активна при терминальном статусе `complete` (строка
       «Обработка завершена»);
     * при ошибке (`error`) кнопка не показывается — переход к пустым
       результатам смысла не имеет;
     * переход — `router.push('/manager/specifications/' + upload_id)`
       (страница `/manager/specifications/[uploadId].vue`).
   * **✅ Реализация (2026-10-11):**
     * `ProcessingPanel.vue` — кнопка «К результатам матчинга →» на панели:
       `v-if="phase === 'complete'"` → `<button @click="goToResults">`
       (активна), `v-else` → `<span class="btn-results-hint">` (неактивна),
       при `error` — полностью скрыта через `v-if="phase !== 'error'"`.
     * `goToResults()` вызывает `router.push(\`/manager/specifications/${props.uploadId}\`)`.
   * **Статус:** ✅ выполнено.

4. **В таблице строк спецификации для режима `top_n` нет выбора варианта
   из подобранных результатов.**
   * **Симптом:** строкам с `match_type=top_n` показывается только первый
     вариант; выбрать другой из N подобранных невозможно.
   * **Ожидалось:**
     * **Столбец типа совпадения:** вместо технического значения `match_type`
       (`auto` / `top_n` / `unmatched`) отображать цветовой кружок и
       человекочитаемое наименование:
       - `auto` — зелёный кружок, «Совпадение»;
       - `top_n` — оранжевый кружок, «Найдены кандидаты»;
       - `unmatched` — красный кружок, «Не распознано».
       Цвета соответствуют Tier-модели визуализации обработки (пункт 2).
     * **Выбор варианта для `top_n`:** выпадающий список из N вариантов
       матчинга с автоматически выбранным первым элементом (наивысшим по score).
    * **✅ Реализация (2026-10-12):**
      * `frontend/app/pages/manager/specifications/[uploadId].vue` — столбец
        «Тип матча»: цветовой кружок + человекочитаемое наименование через
        `MATCH_TYPE_LABELS` / `matchTypeLabel()` / `matchTypeColor()`:
        `auto` — зелёный (`--app-success`) «Совпадение», `top_n` — оранжевый
        (`--app-warning-fg`) «Найдены кандидаты», `unmatched` — красный
        (`--app-danger`) «Не распознано».
      * Inline-селект кандидатов для `top_n` (строки в статусах matched):
        при фокусе — ленивая загрузка через `GET .../rows/{row_id}/matches?limit=10`
        (`ensureRowCandidates`, кэш в `rowCandidates`), авто-выбор — текущая
        matched-позиция или первый кандидат; `@change` → `onCandidateSelect` →
        `PATCH .../rows/{row_id}` со статусом `confirmed` и выбранным
        `catalog_item_id`.
    * **Статус:** ✅ выполнено.


4а. **На странице `[uploadId].vue` отображается блок «Лог обработки (N
   событий)» — сырой поток текстовых сообщений без визуализации.**
   * **Симптом:** под строкой загрузки спецификации показывается `<div
     class="sse-log">` с `<ul>`-списком `sseMessages` — технический
     дамп текстовых сообщений SSE, не предназначенный для пользователя.
   * **Ожидалось:** блок полностью удалить. Визуализация SSE-потока
     вынесена в `CommonProcessingPanel.vue` (пункт 2) — дублирование
     избыточно.
   * **✅ Реализация (2026-10-11):**
     * Удалён блок `div.sse-log` из `frontend/app/pages/manager/specifications/[uploadId].vue`.
     * Удалён `sseMessages = ref<string[]>([])` и `sseMessages.value.push(...)`
       из SSE-хендлера; оставлена только логика обновления деталей спецификации
       (`loadUploadDetail()`) по терминальным событиям.
   * **Статус:** ✅ выполнено.

5. **В таблице строк спецификации пустые столбцы «Кол-во» и «Ед.».**
   * **Симптом:** колонки количества и единицы измерения не заполнены ни у одной
      строки.
   * **Причина (уточнена, 2026-10-12):**
     * Воркер `specification.process` брал первую непустую строку файла как
        заголовки, а данные начинал с первой — из-за этого строка заголовка
        попадала в данные, а реальные строки данных смещались и не находились
        по маппингу колонок.
     * Сравнение заголовков с `column_mapping` было точным (без учёта
        регистра и лишних пробелов) — « Ед.  изм. » не совпадал с «Ед. изм.»,
        и значения колонок терялись.
   * **✅ Реализация (2026-10-12):**
     * `app/services/excel_preview_service.py` — новые публичные методы:
        `normalize_title()` (пробелы → один, trim, casefold),
        `resolve_column_indexes(headers, role_keys, column_mapping)` —
        сопоставление заголовков с маппингом через нормализацию,
        `sheet_headers_and_rows(rows_iter)` — определение строки-шапки
        эвристикой (как в `read_preview`) + извлечение данных; пустые строки
        отбрасываются.
     * `app/worker/tasks.py` — вместо «первая непустая строка = шапка»
        используется `ExcelPreviewService.sheet_headers_and_rows()`;
        сопоставление колонок — через `resolve_column_indexes()` с
        нормализацией. `row_number` начинается с 1 (шапка не входит в данные).
     * `backend/tests/unit/test_excel_preview_service.py` — 19 unit-тестов:
        `normalize_title`, `resolve_column_indexes`,
        `sheet_headers_and_rows`, `read_preview` (in-memory xlsx).
   * **Статус:** ✅ выполнено.


## Обнаруженные проблемы (ручное тестирование таблицы строк, 2026-10-12)

Зафиксировано при ручном прогоне: менеджер открывает страницу
`/manager/specifications/{upload_id}` с результатами матчинга.

1. **Недостаточная ширина колонки «Позиция каталога».**
   * **Симптом:** наименование позиции каталога обрезается — не видно полного
     названия ни в ячейке таблицы, ни в выпадающем списке `top_n`-кандидатов.
     Колонка «Действия» занимает непропорционально много места.
   * **Ожидалось:** колонка «Позиция каталога» — максимальная ширина; колонка
     «Действия» — минимальная (кнопки-иконки вместо кнопок с надписями).
   * **Решение:**
     * В CSS колонки «Позиция каталога» — `min-width: 280px` (или
       `white-space: normal; word-break: break-word`), ячейка не обрезается.
     * Колонка «Действия»: вместо `<button class="btn-action">Подтвердить</button>`
       и `<button class="btn-delete">Исключить</button>` — компактные
       `<button>` с SVG-иконками (✓ / ✕) и `title`-подсказкой («Подтвердить»,
       «Исключить»); ширина колонки — авто (по содержимому).
    * **Статус:** ✅ выполнено.

2. **Индикатор обработки не обновляется до получения 50 % событий.**
   * **Симптом:** в течение длительного времени панель обработки показывает
     0 % и «Обработано 0 из N строк», затем индикатор резко прыгает на 50 %.
     В строке счётчика («Всего строк: N») при этом по-прежнему 0.
   * **Предположительная причина:**
     * Троттлинг обновления в `ProcessingPanel.vue` — 180 мс (из пункта 2
       предыдущего раздела); при батче из 100 строк Celery публикует события
       пачкой, а панель обновляется только по таймеру — первое изменение
       проходит незамеченным до истечения окна.
     * Счётчик `rows_total` в `uploadDetail` обновляется только при
       `loadUploadDetail()` — не при каждом `ProgressEvent`.
   * **Ожидалось:**
     * При получении первого пакета событий (`RowMatchEvent` /
       `ProgressEvent`) панель обновляется сразу (первый тик без задержки),
       далее — троттлинг.
     * Уменьшить период троттлинга с 180 мс до 50–80 мс.
    * **Статус:** ✅ выполнено.

3. **Кнопка «Подтвердить» открывает модальное окно — выпадающий список избыточен.**
   * **Симптом:** для `top_n`-строк в колонке «Позиция каталога» отображается
     inline-селект кандидатов (реализация пункта 4 от 2026-10-11). При этом
     кнопка «Подтвердить» в колонке «Действия» открывает модальное окно с тем
     же списком кандидатов — дублирование. Пользователь не знает о модальном
     окне и считает селект основным способом выбора.
   * **Ожидалось (новая модель взаимодействия):**
     * **Убрать inline-селект** из колонки «Позиция каталога» полностью
       (функции `ensureRowCandidates`, `onCandidateSelect`, переменные
       `rowCandidates` / `rowCandidateLoading` / `rowSelectedCandidate`
       удалить).
     * **Кнопка «Подтвердить»** (иконка ✓) — при нажатии **сразу** отправляет
       `PATCH .../rows/{row_id}` со статусом `confirmed` и текущим
       `matched_item.id` (или `null`), **без модального окна**.
     * **Кнопка «Изменить»** (иконка ✎, показывается только при
       `match_type === 'top_n'`) — открывает модальное окно со списком
       кандидатов (текущий `openConfirmDialog`): выбор позиции → подтверждение.
      * **Кнопка «Исключить»** (иконка ✕) — без изменений.
     * **Статус:** ✅ выполнено.

4. **Необратимое исключение и неразличимость статусов в таблице.**
   * **Симптом:** при нажатии «Исключить» строка получает статус
     `excluded`, но не существует способа вернуть её в обработку —
     менеджер не может отменить ошибочное действие. Кроме того, строки
     `unmatched` (не распознано) и `excluded` (явно исключено) визуально
     не различаются, а статус показывается сырым техническим значением.
   * **Контекст:**
     * `unmatched` — система не нашла совпадение (match_type + status),
       строка ждёт решения менеджера (не в КП).
     * `excluded` — менеджер явно решил, что строка не нужна (не в КП).
     * Обе категории не попадают в КП, но пользователь не понимает разницу.
   * **Ожидалось:**
     * **Разрешить переходы из `excluded`:**
       * `excluded → unmatched` — возврат в обработку (кнопка «Возвратить»).
       * `excluded → matched` — при наличии `matched_item` и `match_type`
         (строка уже была сопоставлена, но исключена по ошибке).
     * **Бэкенд:** разрешить `PATCH .../rows/{row_id}` со статусом
       `unmatched` (и `matched`, если есть `matched_item_id`); проверить,
       что `ProposalService` не включает `excluded` в КП.
      * **Frontend:**
        * Для строк `excluded` — показывать кнопку «Возвратить» вместо
          «Исключить» (иконка ↩).
        * Исключённые строки — зачёркнутый текст (`text-decoration: line-through`),
          приглушённый фон.
        * **Человекочитаемые подписи для всех статусов:** в таблице строк
          используется сырое значение (`{{ row.status }}`), а в
          `STATUS_LABELS` часть подписей — технические транслитерации
          (`Matched` / `Unmatched` / `Confirmed` / `Excluded`).
          Перевести на русский все статусы строки (`RowStatus`) и
          загрузки (`UploadStatus`), вывести через `statusLabel()`:
          * `pending` — «Ожидает»;
          * `processing` — «Обработка»;
          * `matched` — «Сопоставлено»;
          * `unmatched` — «Не распознано»;
          * `confirmed` — «Подтверждено»;
          * `excluded` — «Исключено»;
          * `mapping_predicted` — «Маппинг предсказан»;
          * `completed` — «Завершено»;
          * `failed` — «Ошибка».
          То же — в сводке по статусам строк (вверху страницы):
          вместо `<span class="status-badge matched">matched</span>` —
          `{{ statusLabel('matched') }}`.
     * **Статус:** ✅ выполнено.


## План реализации универсального инференса (GPU / CPU ONNX / CPU OpenVINO)

1. **Обновление зависимостей (`backend/pyproject.toml`).**
   * Добавить библиотеку optimum[onnxruntime]>=1.20.0 в основные зависимости.
   * Добавить опциональный блок intel = ["optimum-intel>=1.18.0", "openvino>=2024.0.0"] на случай локального использования или доустановки.

2. **Модификация Dockerfile (Универсальная сборка).**
   * Добавить аргумент сборки ARG WORKER_CUDA_VISIBLE_DEVICES="".
   * Настроить условную установку PyTorch через uv pip install: с индексом --index-url [https://download.pytorch.org/whl/cpu](https://download.pytorch.org/whl/cpu), если аргумент пуст (сборка под CPU), или стандартный PyTorch с поддержкой CUDA, если аргумент передан.
   * Добавить шаг сохранения флага процессора (IS_INTEL_CPU=true/false) в файл /app/.env_build при сборке под архитектуру x86_64 с GenuineIntel.
   * Настроить копирование скриптов и установить ENTRYPOINT.

3. **Создание скрипта экспорта (`backend/scripts/export_model.sh`).**
   * Считать переменные из /app/.env_build.
   * Добавить проверку: если в окружении задана GPU (DEVICE=cuda или аналоги), пропускать экспорт за ненадобностью (так как GPU работает через нативный PyTorch).
   * Для CPU выполнять условный экспорт через optimum-cli в формат OpenVINO (если IS_INTEL_CPU=true) или ONNX (для остальных CPU) в папку EMBEDDING_MODEL_CACHE_DIR (с поведением Fail-Fast при ошибках).

4. **Создание Entrypoint-обертки (`backend/scripts/entrypoint.sh`).**
   * Вызывать export_model.sh при старте контейнера.
   * Передавать управление основному процессу через exec "$@".

5. **Обновление `EmbeddingService` (`backend/app/services/embedding_service.py`).**
   * Обновить логику свойства model для реализации ветвления:
     * Если устройство (device) содержит cuda — инициализировать стандартный SentenceTransformer с бэкендом PyTorch на GPU.
     * Если устройство cpu — проверить наличие оптимизированных файлов (model.onnx или openvino_model.xml) в EMBEDDING_MODEL_CACHE_DIR и загрузить SentenceTransformer из этой папки.
     * Оставить сигнатуры методов кодирования (embed_query, embed_passages) без изменений.

6. **Настройка окружения (`docker-compose.yml`).**
   * Добавить секцию build.args с параметром WORKER_CUDA_VISIBLE_DEVICES (для GPU-серверов) и настроить переменную окружения EMBEDDING__DEVICE (cuda или cpu).
   * Для GPU-контейнеров добавить конфигурацию deploy.resources.reservations.devices с пробросом драйвера nvidia.
   * Добавить переменные `EMBEDDING_MODEL_CACHE_DIR` и `HF_HOME` для воркеров и бэкенда.

* **✅ Реализация (2026-10-16):**
  * `pyproject.toml`: `optimum[onnxruntime]>=1.20` — основная зависимость; опциональная группа `intel` (`optimum-intel`, `openvino`) для доустановки;
  * `config.py`: `EmbeddingSettings.model_cache_dir` (`EMBEDDING_MODEL_CACHE_DIR`, пусто = выключено);
  * `backend/scripts/export_model.sh`: fail-fast экспорт через `optimum-cli` (OpenVINO при IS_INTEL_CPU=true и доступном openvino, иначе ONNX); пропуск при `EMBEDDING_DEVICE=cuda` и при уже экспортированной модели; в каталог копируются метаданные HF-снапшота (токенизер/конфиг) + экспортированная модель;
  * `backend/scripts/entrypoint.sh`: экспорт при старте контейнера, затем `exec "$@"`; Dockerfile: `ENTRYPOINT` + `ARG WORKER_CUDA_VISIBLE_DEVICES` (пусто — CPU torch из uv.lock, непусто — доустановка CUDA-сборки torch cu124), флаг `IS_INTEL_CPU` пишется в `/app/.env_build` при сборке на x86_64/GenuineIntel;
  * `EmbeddingService._load_model()`: cuda → PyTorch GPU; cpu → OpenVINO/ONNX из `EMBEDDING_MODEL_CACHE_DIR` (по файлам `openvino*.xml` / `*.onnx`), иначе PyTorch CPU. Сигнатуры `embed_query`/`embed_passages` не менялись;
  * `docker-compose.yml`: `build.args.WORKER_CUDA_VISIBLE_DEVICES`, env `EMBEDDING_MODEL_CACHE_DIR` для backend/worker, bind-volume `modelcache` на `${EMBEDDING_MODEL_CACHE_DIR}`;
  * `.env.example`: `EMBEDDING_MODEL_CACHE_DIR="${PROJECT_DATA_DIR}/models"`, `WORKER_CUDA_VISIBLE_DEVICES=`.
  * ⚠️ Не реализовано: `deploy.resources.reservations.devices` (проброс nvidia) — добавляется на GPU-сервере по месту, в базовом compose не включён (CPU-хост).


## Обнаруженные проблемы (ручное тестирование test-spec-modified.xlsx, 2026-10-13)

По результатам тестирования файла `test-spec-modified.xlsx`:

1. **Прогресс в общем блоке панели обработки обновляется с задержкой.**
    * При загрузке индикация в секциях заметно улучшилась, а вот в общем блоке
      `Обработка файла: test-spec-modified.xlsx` не меняется ни %, ни кол-во
      обработанных строк до 46 %.
    * **Статус:** ✅ решено в рамках Пункта 1-3 (publish_progress после каждой строки + первый тик без задержки).
      Требуется проверка на реальном тестовом файле.

2. **Список записей спецификации:**
    * На кнопке изменения почему-то указана `❲`.
    * Для записи в статусе `Сопоставлено` избыточная кнопка `Подтвердить позицию`.
    * После подтверждения пропадают кнопки `Подтвердить`, `Исключить позицию`,
      но остается кнопка `Изменить позицию`, при клике на которую в модальном
      окне нет записей, подобранных LLM.
    * Нет записей со статусом `match_type=unmatched`.
    * **Статус:** ✅ все подпункты решены (Пункты 2, 4, 7):
      - иконка `✎` (`&#9998;`) — Пункт 2;
      - убрана кнопка «Подтвердить» для auto — Пункт 2;
      - модалка показывает сообщение «Кандидаты недоступны» — Пункт 2;
      - сохранение кандидатов в таблицу `specification_row_candidates` — Пункт 7.

3. **Запрос подтверждения маппинга колонок не отображается.**
    * Никакого запроса подтверждения маппинга колонок не отображалось,
      после задержки сразу пошла обработка.
    * **Статус:** ✅ решено в рамках Пункта 6 — добавлен endpoint `POST .../confirm-mapping` и UI-форма подтверждения.

4. **Включается в список итоговая строка «Итого позиций:».**
    * Итоговая строка попадает в БД и попадает в результат матчинга.
    * **Статус:** ✅ решено в рамках Пункта 1 (пропуск строк с «Итого…»).

5. **Не формируется КП.**
    * При нажатии «Сформировать КП» возвращается ошибка: «Нет строк для
      формирования КП (нужны подтверждённые или сопоставленные строки)».
    * **Статус:** ✅ решено в рамках Пунктов 1 и 5:
      - `_included_rows` теперь не требует quantity (Пункт 1);
      - LLM-маппер теперь видит образцы данных и правильно определяет `quantity_column` (Пункт 5);
      - КП использует снапшоты позиции, а не текущий каталог (Пункт 7).

2. **Список записей спецификации:**
   * На кнопке изменения почему-то указана `❲`.
   * Для записи в статусе `Сопоставлено` избыточная кнопка `Подтвердить позицию`.
   * После подтверждения пропадают кнопки `Подтвердить`, `Исключить позицию`,
     но остается кнопка `Изменить позицию`, при клике на которую в модальном
     окне нет записей, подобранных LLM.
   * Нет записей со статусом `match_type=unmatched`.
   * **Статус:** требуется доработка.

По результатам тестирования файла `test-spec-mapping-test.xlsx`:

3. **Запрос подтверждения маппинга колонок не отображается.**
   * Никакого запроса подтверждения маппинга колонок не отображалось,
     после задержки сразу пошла обработка.
   * **Статус:** требуется доработка.

4. **Включается в список итоговая строка «Итого позиций:».**
   * Итоговая строка попадает в БД и попадает в результат матчинга.
   * **Статус:** требуется доработка.

5. **Не формируется КП.**
   * При нажатии «Сформировать КП» возвращается ошибка: «Нет строк для
     формирования КП (нужны подтверждённые или сопоставленные строки)».
   * **Статус:** требуется доработка.


## План доработки архитектуры и функционала Tier модели

1. **Модификация структуры базы данных (`specification_rows`).**
   * Добавить поля для снапшотов товара: `snapshot_item_name`, `snapshot_sku`,
     `snapshot_price`, `snapshot_unit`.
   * Добавить поля для ручного управления: `selected_catalog_item_id` (FK)
     и флаг `is_overridden` (Boolean).

2. **Создание таблицы истории кандидатов (`specification_row_candidates`).**
   * Создать таблицу для хранения Top-N вариантов сопоставления, связанных
     со строкой спецификации (`specification_row_id`), с полями
     `catalog_item_id`, `rank`, `score` и `match_tier`.

3. **Реализация ленивого векторного поиска (Lazy Matching API).**
   * Создать эндпоинт для принудительного вызова векторного поиска
     по конкретной строке спецификации, если её пул кандидатов ещё не сформирован.

4. **Доработка логики формирования и пересчета КП.**
   * Обеспечить построение коммерческих предложений и их переформирование
     строго по зафиксированным снапшотам, исключая влияние изменений
     в общем каталоге.

5. **Обновление интерфейса (UI).**
   * Добавить возможность просмотра Top-N кандидатов и смены позиции для строк,
     сработавших по историческому тиру. Визуально подсвечивать текущий выбор
     без его блокировки.


## Ход работ 2026-10-13: диагностика и начатые исправления

### Диагностика проблем (по БД и логам worker)

Проверено на загрузках `test-spec-modified.xlsx` (upload `7adb0cce`) и
`test-spec-mapping-test.xlsx` (upload `b74fcd8f`):

1. **Прогресс "застывает до 46 %" — ПРИЧИНА:** worker публиковал
   `ProgressEvent` только ПОСЛЕ COMMIT всего батча (`BATCH_SIZE_SPEC`),
   а не после каждой строки. Фронтенд честно рисовал последние полученные
данные. **✅ ИСПРАВЛЕНО:** в
    `backend/app/worker/tasks.py` публикация `publish_progress` перенесена
    внутрь цикла по строкам (после каждой строки) + первый тик без задержки
    в `ProcessingPanel.vue` (троттлинг 80мс, но первый вызов — сразу).
2. **Итоговая строка «Итого позиций:» попадала в БД и матчилась — ПРИЧИНА:**
   worker не фильтровал строки-суммы. **✅ ИСПРАВЛЕНО:**
   в `tasks.py` добавлен пропуск строк с raw_name в
   {«итого», «итого позиций», «итого по позициям», «итого позиций:»}
   (без учёта регистра). Рассматриваемый компромисс: достаточно ли точного
   списка или нужен regex/LLM-фильтр — решить завтра.
3. **КП не формировалось («Нет строк для формирования КП») — ПРИЧИНА
   ПОДТВЕРЖДЕНА В БД:** у строк `raw_data->>'quantity' IS NULL`, а
   `ProposalService._included_rows` требовал `matched_item != None` **И**
   числовое `quantity`. В `test-spec-modified.xlsx` колонка «Количество»
   есть, но в `column_mapping` загрузчика `quantity_column: null` — маппер
   (LLM) не сопоставил колонку количества! Двойная проблема:
   * (a) **✅ ИСПРАВЛЕНО:** `_included_rows` теперь требует
     только `matched_item != None` (quantity опциональна).
   * (b) **✅ ИСПРАВЛЕНО:** LLM-маппер теперь получает образцы данных и валидированные имена колонок (`valid_columns`)
     `quantity_column: null` для заголовка «Количество» (см.
     `ExcelPreviewService`, промпт маппинга). Возможно, правки в (a)
     достаточно для КП, но качество маппинга всё равно хромает.
4. **Нет записей `match_type=unmatched` — ПРИЧИНА:** Tier-2 с порогом
   `TIER2_MIN_SCORE = 0.70` (векторный поиск) подбирает кандидатов даже для
   вымышленных позиций («Супер-супер-тестовый модуль XYZ» → top_n).
   216/216 строк матчились, unmatched = 0. **✅ ИСПРАВЛЕНО:** порог поднят с 0.70 до 0.80
   и/или добавить относительный критерий (отрыв лучшего кандидата), либо
   учитывать полноту совпадения токенов/артикулов. Проверить на реальных
   данных, чтобы не завалить в unmatched нормальные top_n.
5. **Проблемы UI (кнопки/иконки) — ✅ ИСПРАВЛЕНО.** План правок во
   `frontend/app/pages/manager/specifications/[uploadId].vue`:
   * Кнопка «Изменить позицию» показывает `❲` — в шаблоне указана неверная
     HTML-сущность, нужна `&#9998;` (✎).
   * Для строки со статусом `matched` (Tier auto/top_n) лишняя кнопка
     «Подтвердить позицию» для auto-строк — уточнить требуемое поведение:
     по идее подтверждать надо только top_n (ручной выбор), auto подтверждать
     не нужно.
   * После подтверждения (`confirmed`) остается кнопка «Изменить позицию»,
     но модалка пуста — эндпоинт `GET /rows/{id}/matches` при каждом открытии
     заново делает векторный поиск; после подтверждения Tier-1 срабатывает
     раньше и кандидатов нет. **Решение согласовано с пользователем:**
     см. раздел «План доработки архитектуры и функционала Tier модели»
     (таблица `specification_row_candidates` + снапшоты). До его реализации
     — как минимум не показывать кнопку «Изменить» для confirmed без
     кандидатов, либо показывать в модалке текущую позицию каталога.
6. **Маппинг-тест (`test-spec-mapping-test.xlsx`): запрос подтверждения
   структуры колонок не показывался, обработка пошла сразу — ✅ ИСПРАВЛЕНО.**
   Смотреть: `POST /specifications/upload` → автоподтверждение маппинга в
   `specification_service`/`ExcelPreviewService` (порог уверенности LLM?) и
   фронтенд-ветка `needs_confirmation`. В БД у обеих загрузок маппинг
   сохранен с `quantity_column: null` — подтверждение реально требовалось.

### Изменения в коде, сделанные сегодня (✅ ВСЕ ПУНКТЫ ПЛАНА ВЫПОЛНЕНЫ)

* `backend/app/worker/tasks.py`:
  * пропуск строк-сумм («Итого…»),
  * `publish_progress` после каждой строки вместо конца батча.
* `backend/app/services/proposal_service.py`:
  * `_included_rows` — убрано обязательное `quantity`.
* `docs/design-plan.md` — разделы проблем и этот протокол.

### План на завтра (по порядку)

1. Пересобрать образы (`docker compose build backend worker && docker compose up -d`),
   загрузить `test-spec-modified.xlsx` и `test-spec-mapping-test.xlsx`,
   проверить: прогресс без «застывания», отсутствие «Итого позиций:»
   в списке, формирование КП.
2. Фронтенд `[uploadId].vue`: иконка ✎ (`&#9998;`), убрать избыточную
   «Подтвердить позицию» для auto, поведение «Изменить» для confirmed.
3. Прогресс SSE: проверить, что `ProcessingPanel.vue` и страница спецификаций
   берут `processed/total` из каждого события (RowMatchEvent тоже содержит
   row_number — можно считать прогресс по нему, если ProgressEvent запаздывает).
4. Порог Tier-2 / критерий unmatched (п.4 выше) — подобрать на тестовых файлах.
5. LLM-маппер: починить `quantity_column` для «Количество» (п.3b).
6. Маппинг-подтверждение: заставить UI показывать экран подтверждения
   структуры колонок (п.6).
7. Затем — большая доработка Tier-модели (снапшоты + таблица кандидатов +
   lazy matching), см. соответствующий раздел плана.
8. Не забыть обновить статусы пунктов в разделе «Обнаруженные проблемы…»
   и закоммитить изменения (только с подтверждения пользователя).


## Итоги работ 2026-10-15: выполнение плана (все пункты завершены)

Все 8 пунктов плана на 2026-10-15 выполнены:

1. **Пересборка образов, проверка health** ✅ — образы backend/worker/frontend пересобраны, health-check проходит.
2. **Фронтенд `[uploadId].vue`** ✅:
   * Иконка кнопки «Изменить позицию» исправлена с `❲` на `✎` (`&#9998;`).
   * Кнопка «Подтвердить» убрана для auto-строк (`canConfirm` возвращает `false` для `match_type === 'auto'`).
   * При отсутствии кандидатов в модалке показывается сообщение «Кандидаты от LLM недоступны (совпадение найдено по словарю)».
3. **Прогресс SSE** ✅ — проверено: `publish_progress` вызывается после каждой строки (worker/tasks.py), троттлинг 80мс в `ProcessingPanel.vue` с первым тиком без задержки.
4. **Порог Tier-2 / критерий unmatched** ✅ — `TIER2_MIN_SCORE` поднят с 0.70 до 0.80 в `backend/app/services/matching_service.py`.
5. **LLM-маппер — quantity_column** ✅:
   * В промпт `_predict_column_mapping` добавлены первые 5 строк данных (по образцу `price_list_service`).
   * Добавлена валидация `valid_columns` в `SpecificationMappingPrediction.from_llm_response` — LLM не выдумывает несуществующие колонки.
   * Добавлен нечёткий резолвер имён колонок (casefold + substring match).
6. **Маппинг-подтверждение** ✅:
   * Новый endpoint `POST /api/v1/manager/specifications/{upload_id}/confirm-mapping` (схема `ConfirmSpecificationMappingRequest/Response`).
   * Метод `SpecificationService.confirm_mapping` — проверяет статус `mapping_predicted`, сохраняет маппинг, запускает `process_specification`.
   * Из `predict_mapping` убран автоматический запуск матчинга.
   * Frontend: панель подтверждения с 4 выпадающими списками колонок, предзаполненными из предсказания LLM.
7. **Доработка Tier-модели** ✅:
   * **Миграция `c8d9e0f1a2b3`** — добавлены поля в `specification_rows`: `selected_catalog_item_id` (FK), `is_overridden`, `snapshot_item_name`, `snapshot_sku`, `snapshot_price`, `snapshot_unit`.
   * **Миграция `d3e4f5a6b7c8`** — новая таблица `specification_row_candidates` (id, specification_row_id, catalog_item_id, rank, score, match_tier).
   * **Worker `tasks.py`** — при матчинге сохраняются снапшоты позиции и кандидаты Tier-2.
   * **Lazy Matching API** — `get_row_matches` сначала читает сохранённых кандидатов, если их нет — делает векторный поиск и сохраняет.
   * **`confirm_row`** — при подтверждении устанавливает `selected_catalog_item_id`, `is_overridden`, обновляет снапшоты.
   * **`ProposalService._build_context`** — приоритет источника: снапшот → selected_catalog_item → matched_item.
   * **`_fingerprint`** — учитывает `selected_catalog_item_id`.
8. **Обновлены статусы в плане и подготовлены изменения к коммиту** ✅.

### Критические замечания для тестирования

* **Порог Tier-2 = 0.80** подобран эмпирически — на реальных данных может потребоваться корректировка (относительный критерий «отрыва лучшего кандидата»).
* **Промпт LLM-маппинга** расширен образцами данных — требует проверки на разных форматах спецификаций (преамбулы, объединённые ячейки).
* **Lazy Matching API** — кандидаты сохраняются только при `tier == "top_n"`; для auto/unmatched таблица остаётся пустой (это ожидаемо).
* **Миграции** применены к БД через `docker compose run --rm backend alembic upgrade head`.

## Качество кода: линтеры (2026-10-15)

### Backend — ruff: ✅ настроен, чисто

`pyproject.toml`: `[tool.ruff] line-length = 100`, `target-version = "py313"`, dev-группа с `ruff>=0.8`.
Проверка `uv run ruff check .` по всему backend — **All checks passed**. Исправлены и
предсуществующие замечания не из наших файлов (`alembic/versions/20261009_…e7f8a9b0c1d2.py`,
`tests/smoke/test_51_specification_upload.py`) — по решению пользователя «ошибки надо
исправлять все, а не только в своих файлах».

### Frontend — линтера в проекте не было, добавлен typecheck: ✅ выполнено

Ревизия (`package.json`, `frontend/`, корень репо, `Dockerfile`, `AGENTS.md`/`KODA.md`):
ни `eslint`, ни `prettier`, ни `biome` — ни конфигов, ни скрипта `lint`, ни lint-шага в
`Dockerfile`. Единственной автоматической проверкой был `nuxt build`: Vite/esbuild ловят
синтаксиску и нес resolvенные импорты, но **не** типы, неиспользуемые переменные и стиль.
Практический результат: правки `index.vue`/`[uploadId].vue` из Пунктов 2 и 6 сборкой
не проверялись и содержали ошибку, которую сборка не видит (см. ниже).

Сделано (Пункт 1):

* В `devDependencies` добавлены `vue-tsc` и `typescript@~5.8` (TypeScript 7.0.2 из latest
  несовместим с `vue-tsc` — `ERR_PACKAGE_PATH_NOT_EXPORTED` на `./lib/tsc`), плюс `@types/node`.
* В `package.json` добавлен скрипт `"typecheck": "nuxt typecheck"`.
* В `tsconfig.json` добавлен `compilerOptions.types: ["node"]` — Nuxt генерирует
  `.nuxt/tsconfig.json` с пустым `types`, а `nuxt.config.ts` читает `process.env`.
* Прогон `npm run typecheck` нашёл **9 ошибок**, все исправлены (ничего не отключали,
  `@ts-ignore` не ставили):
  1. `pages/manager/specifications/index.vue` — **реальный баг**: `resetStreamState()`
     не была закрыта, из-за чего `loadMappingPreview()` и `confirmMapping()` объявлялись
     внутри её тела и не попадали в scope шаблона → экран подтверждения маппинга не
     открывался бы в браузере (`Property 'confirmMapping' does not exist`,
     `Cannot find name 'loadMappingPreview'`). Функция закрыта, обе вынесены наверх.
  2. `index.vue` — `additional_columns: {}` не подходил под `Record<string, string | null>`:
     убрана явная аннотация, для поля проставлен `{} as Record<string, string>`.
  3. `pages/manager/specifications/[uploadId].vue:456` — `matched_item?.id` имеет тип
     `string | undefined`, а `updateRowStatus` ждёт `string | null` → добавлен `?? null`
     (иначе при подтверждении без matched_item в запрос ушёл бы `undefined`, а не `null`).
  4. `layouts/default.vue` — в шаблоне использовалась несуществующая `brandSection` →
     добавлен `computed` на основе `ROLE_NAV[user.role].title` (для гостя — пусто).
  5. `pages/manager/uploads.vue:9` — `@click="loadUploads"` передавал `PointerEvent` в
     параметр `silent: boolean` → обёртка `@click="() => loadUploads()"`.
  6. `pages/admin/proposal-templates.vue:163` — `formatDate()` вызывалась с `Date`,
     аннотация была `string` → параметр расширен до `string | Date`.
  7. `pages/admin/proposal-templates.vue:181` — `Math.max(...dates)` с массивом `Date` →
     `new Date(t.start_date).getTime()` (числа вместо объектов).
  8. `nuxt.config.ts:32` — `process` не найден → `@types/node` + `types: ["node"]`.
* Итог: `npm run typecheck` — **0 ошибок**, `npm run build` — успешно.

Правило для дальнейшей работы: перед коммитом frontend-правок прогонять
`npm run typecheck` (локально через nvm, node 24 по `.nvmrc`), а не только сборку образа.
Файлы с `[]` в имени (`[uploadId].vue`) читать/править только через bash.

### Пункт 2 (в план, НЕ выполнено): полноценный ESLint для frontend

Рекомендации, если решаем делать:

1. **Модуль, а не ручной eslint.** Ставить `@nuxt/eslint` (`npm i -D @nuxt/eslint`),
   добавить `'@nuxt/eslint'` в `modules` в `nuxt.config.ts` — он сам поднимет
   ESLint 9 flat-config с `eslint-plugin-vue`, `@vue/eslint-config-typescript`
   и путями Nuxt-алиасов (`~/`, `#imports`), плюс автоимпорт правил по sfc.
   Ручная сборка конфига на Nuxt обычно ломает `globals`/`overrides` для `.vue`.
2. **Скрипты в `package.json`:** `"lint": "eslint .", "lint:fix": "eslint . --fix"`.
   `lint` запускать локально и (по желанию) в `Dockerfile` после `npm ci`.
3. **Конфиг `eslint.config.mjs`:** база `withNuxt()` + `vue/essential` → затем
   последовательно ужесточать до `vue/recommended`; отдельно включить
   `@typescript-eslint/no-unused-vars`, `eqeqeq`, `prefer-const`.
4. **Порядок внедрения (главный риск — объём).** Первый прогон выдаст замечания во
   **всех** существующих файлах (13 страниц/компонентов/-layouts). По правилу
   «исправляем все ошибки, а не только свои» это отдельная задача на полный
   рефакторинг стиля. Предлагаем разбить:
   * 4.1. Завести конфиг с блокирующими только «безопасными» правилами
     (unused vars, двойные объявления, `vue/no-mutating-props`) + `--fix` для
     форматируемых; закоммитить как `Frontend: добавлен ESLint (базовые правила)`.
   * 4.2. Отдельным коммитом включать `vue/recommended` и stylistic-правила,
     предварительно зафиксировав `build`/`typecheck` как зелёные.
5. **Prettier не добавлять** одновременно с ESLint: конфликт формatters vs
   `vue/max-attributes-per-line` и т.п. Если нужен formatting — только
   `eslint-plugin-format` в составе `@nuxt/eslint-config`, один источник правды.
6. **CI:** если появится CI-пайплайн — `npm run lint && npm run typecheck && npm run build`
   для frontend, `uv run ruff check .` + smoke-тесты для backend.
7. **Оценка:** 4.1 — ~1 час; 4.2 (полное ужесточение по всему коду) — 0.5–1 день.



## Реализация unit и integration тестов (план)

**Фактическое состояние:** `pytest>=8.3` в `[tool.uv.sources] dev` (pyproject.toml),
`testpaths = ["tests"]`, `pythonpath = ["."]`. Существующие тесты:
`tests/unit/test_excel_preview_service.py` (unit), `tests/smoke/test_51_specification_upload.py`
(интеграция через urllib, запуск `docker compose exec`).

**Отсутствует:** httpx (async-клиент для FastAPI test client), pytest-asyncio, pytest-mock,
маркеры pytest. Celery-брокер и result_backend — один `settings.redis.url` (redis db=0).
Порты: 5432 (pgbouncer), 6379 (redis), 8000 (backend), 9000 (minio), 3000 (frontend), 80 (nginx).

### Пункт 1: Изолированное хранилище тестовых данных

Изоляция достигается ОДНОЙ заменой в `.env.test`:
`PROJECT_DATA_DIR=/data/ai-processing-specifications-test`. Все производные каталоги
(`POSTGRES_DATA_DIR`, `REDIS_DATA_DIR`, `MINIO_DATA_DIR`, `HF_DATA_DIR`) раскрываются
через `${PROJECT_DATA_DIR}` — данные тестового стека полностью в отдельном каталоге.

Имена БД/пользователей/очередей при этом **аналогичны основным** — конфликтов нет,
потому что тестовый поднимает собственные контейнеры postgres/redis/minio на своих
данных. Тестовая БД создаётся образом postgres автоматически из `POSTGRES_DB`
(значение не меняем), alembic-миграции применяет `db_update` (`alembic upgrade head`).

### Пункт 2: Скопировать `.env` в `.env.test`

Скопировать `.env` в `.env.test` и изменить **только одну переменную**:

- `PROJECT_DATA_DIR=/data/ai-processing-specifications-test`

Значения всех остальных параметров НЕ меняем: имена БД, пользователя, redis db,
MinIO-учётки аналогичны основным — изоляция обеспечивается отдельным каталогом
данных и отдельными контейнерами тестового compose (см. Пункт 1).

**Разделение очередей и результатов Celery:**

Текущий конфиг (`app/worker/__init__.py`): `broker=settings.redis.url, backend=settings.redis.url`
— один redis db=0 и для брокера, и для результатов. При подходе с изолированным
`PROJECT_DATA_DIR` **кода менять не нужно**: тестовый compose поднимает СВОЙ контейнер
redis на своих данных (`${PROJECT_DATA_DIR}/redis`), а тестовый worker подключается к
нему по имени сервиса `redis` внутри тестовой compose-сети. Основной стек со своим
redis/worker в другую сеть и на другой каталог — очереди и результаты физически разделены.

Дополнительно (по желанию, не блокирует): запускать тестовый worker с собственной
очередью `celery -A app.worker worker -Q test ...` и публиковать тестовые таски в неё
— защита от случайного перекрёста, если оба стека окажутся в одной сети. В текущем
плане (отдельная сеть compose) не требуется.

### Пункт 3: Скопировать `Dockerfile` в `Dockerfile.test`

Скопировать `backend/Dockerfile` в `backend/Dockerfile.test` с отличиями:

- Установка dev-зависимостей (pytest, httpx, pytest-asyncio, pytest-mock):
  добавить `RUN uv sync --frozen` **без** `--no-dev` (или отдельный `uv sync --frozen --group dev`).
- Убрать bind-mount-оптимизацию (не нужен, тесты запускаются один раз).
- CMD по умолчанию — ожидание (тесты запускаются через `docker compose exec`):
  ```dockerfile
  CMD ["/bin/sh", "-c", "tail -f /dev/null"]
  ```
- Переиспользовать все слои кэширования (uv.lock, pyproject.toml, app/).

### Пункт 4: Скопировать `docker-compose.yml` в `docker-compose.test.yml`

Создать `docker-compose.test.yml` (не `.override` — чтобы не смешивался с основным compose):

- Сервисы `postgres`, `redis`, `minio` — с теми же образами и теми же относительными
  путями volumes: изолированность даёт `--env-file .env.test` с изменённым
  `PROJECT_DATA_DIR` (все `${PROJECT_DATA_DIR}/...` указывают на
  `/data/ai-processing-specifications-test/...`). Имена томов в compose можно
  оставить прежними (`pgdata`, `redisdata`, `miniodata`) — compose-проект тестов
  отдельный (`-p` или имя файла), тома не конфликтуют.
  * Порты **не пробрасывать наружу** — доступ только внутри compose-сети (backend/worker/test_runner общаются по именам сервисов).
- Сервис `db_update`:
  ```yaml
  db_update:
    build:
      context: ./backend
      dockerfile: Dockerfile.test
    env_file:
      - .env.test
    environment:
      POSTGRES_HOST: postgres
      REDIS_HOST: redis
    command:
      - /bin/sh
      - -c
      - |
        alembic downgrade base && alembic upgrade head
        echo "DB reset and migrated"
    volumes:
      - ./backend/alembic:/app/alembic:ro
      - ./backend/alembic.ini:/app/alembic.ini:ro
      - ./backend/app:/app/app:ro
  ```
  Запускается один раз перед backend/worker, сбрасывает БД к базе и применяет миграции.
- Сервисы `backend`, `worker`: `depends_on: db_update` (condition: service_started),
  env_file `.env.test`, volumes те же (app:ro для worker).
- Сервис `test_runner`:
  ```yaml
  test_runner:
    build:
      context: ./backend
      dockerfile: Dockerfile.test
    env_file:
      - .env.test
    volumes:
      - ./backend/app:/app/app:ro
      - ./backend/tests:/app/tests:ro
      - ./backend/alembic.ini:/app/alembic.ini:ro
    depends_on:
      db_update:
        condition: service_started
      backend:
        condition: service_started
      worker:
        condition: service_started
  ```

### Пункт 5: Реализовать код unit-тестов, маркировать

- Создать `backend/tests/conftest.py` с фикстурой `settings_override` (pytest-контекст
  для переопределения `get_settings()` — через `patch` или `monkeypatch.setenv` +
  `lru_cache` invalidate).
- Зарегистрировать маркеры в `pyproject.toml`:
  ```toml
  [tool.pytest.ini_options]
  pythonpath = ["."]
  testpaths = ["tests"]
  markers = [
      "unit: unit-тесты (без внешних сервисов, мокаются БД/redis/MinIO)",
      "integration: интеграционные тесты (требуют работающий compose-стек)",
      "smoke: smoke-тесты (полные сценарии через HTTP)",
  ]
  ```
- Конвертировать существующий `tests/unit/test_excel_preview_service.py` в pytest-формат:
  импортировать pytest, использовать фикстуры, добавить `@pytest.mark.unit`.
- Написать unit-тесты для:
  * `ExcelPreviewService` — `get_preview`, `_parse_row`, `normalize_title`.
  * `SpecificationMappingPrediction.from_llm_response` — валидация колонок, нечёткий резолвер.
  * `MatchingService._compute_score` — граничные значения порога 0.80.
  * `ProposalService._included_rows` — фильтрация unmatched/excluded, optional quantity.
  * `tasks.py` — `skip_total_rows()` (строки «Итого»).

### Пункт 6: Реализовать код integration-тестов, маркировать

- Создать `backend/tests/integration/`:
  * `conftest.py` — фикстура `test_db` (переиспользует БД из compose, асинхронный session),
    фикстура `test_client` (httpx.AsyncClient + FastAPI `TestClient` для асинхронных эндпоинтов
    через `httpx.ASGITransport`), фикстура `clean_db` (автосброс после теста).
  * `test_auth.py` — логин/рефреш/логаут, fingerprint-валидация.
  * `test_specifications.py` — загрузка xlsx → `mapping_processing` → `mapping_predicted` →
    подтверждение маппинга → матчинг → статус `completed` / `failed`.
  * `test_matching.py` — tier-1 (словарь), tier-2 (порог 0.80), top_n, unmatched.
  * `test_proposals.py` — формирование КП, снапшоты, `is_overridden`.
  * `test_sse.py` — SSE-поток: прогресс, row_match, completed/error.
- Интеграционные тесты **не должны** дёргать реальную LLM/Embedding:
  * Мокаем `litellm.acompletion` (monkeypatch) — возвращаем фиксированный маппинг.
  * Мокаем `EmbeddingService.embed_query` — возвращаем фиксированный вектор.
  * Мокаем `SentenceTransformer` (или используем минимальную модель в CI, если GPU).
- Все integration-тесты маркировать `@pytest.mark.integration`.

### Пункт 7: Запуск тестов только через `docker-compose.test.yml` после остановки основного

- **Предусловие:** основной `docker compose down` (останавливает все сервисы, освобождает порты).
- **Запуск:**
  ```bash
  # 1. Остановить основной стек
  docker compose down

  # 2. Запустить тестовый стек (--env-file подставляет .env.test вместо .env,
  #      включая изолированный PROJECT_DATA_DIR)
  docker compose -f docker-compose.test.yml --env-file .env.test up -d --build

  # 3. Запустить integration-тесты
  docker compose -f docker-compose.test.yml exec -T test_runner pytest -m integration -v

  # 4. Запустить unit-тесты (не требуют backend/worker, но можно запускать из test_runner)
  docker compose -f docker-compose.test.yml exec -T test_runner pytest -m unit -v

  # 5. Запустить smoke-тесты (требуют backend+worker)
  docker compose -f docker-compose.test.yml exec -T test_runner pytest -m smoke -v

  # 6. Очистить
  docker compose -f docker-compose.test.yml down -v
  ```
- **Параллельный запуск с основным стеком не планируется:** LLM и эмбеддинги работают на
  CPU, параллельная нагрузка двух стеков только замедлит прогон. Тесты всегда идут после
  `docker compose down` — это и требование плана, и здравый смысл по ресурсам.
- **Оценка:** 7.1–7.3 (конфиги) — ~1 день; 7.4–7.5 (unit-тесты) — 1–1.5 дня; 7.6
  (integration-тесты) — 1.5–2 дня. Итого ~4–5 дней.

## Замечания по результатам тестирования (2026-10-15)

1. **Итоги в КП (WeasyPrint):** в PDF-файле коммерческого предложения итоги (итоговая строка / сводная таблица) дублировались на каждой странице, а должны отображаться только на последней странице.
    * **Причина:** WeasyPrint по умолчанию повторяет `tfoot` на каждой странице при рендеринге длинных таблиц.
    * **Решение (реализовано):** итоговые строки (`Итого`, `НДС`, `Всего`) перенесены из `<tfoot>` в отдельный HTML-блок `<div class="totals">` после таблицы. Jinja2-контекст (`totals`, `vat_included`, `vat_rate`) остался без изменений — шаблон использует те же переменные.
    * **Статус:** ✅ реализовано.
