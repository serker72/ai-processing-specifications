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
* **Реализация:**
  * ✅ Эндпоинт `POST /api/v1/manager/specifications` (manager role).
  * ✅ `SpecificationRepository` — CRUD для `SpecificationUpload` и `SpecificationRow`.
  * ✅ `SpecificationService` — потоковая загрузка в MinIO, превью 50 строк, LLM-предсказание маппинга.
  * ✅ `SpecificationMappingPrediction` — Pydantic-схема ответа LLM (name, quantity, unit, price, additional_columns).
  * ✅ DI-провайдеры для `SpecificationRepository` и `SpecificationService`.
  * ✅ Smoke-тест: загрузка Excel → MinIO + превью + LLM-маппинг → 201 Created.

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
  * Рабочий стол спецификации. Таблица с виртуальным скроллом, подключенная к SSE.
  * Цветовое кодирование: зеленый (Точное совпадение), желтый (ТОП-5 на выбор), красный (Не найдено).
  * Действия пользователя (Выбрать из списка, Исключить, Подтвердить) записывают связи в базу `HistoricalMatch` для Tier-1.

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
* **Pricelists** (`app/pages/admin/pricelists.vue`): загрузка Excel (multipart через `$api`) + история загрузок со статусами обработки.
* **Catalog** (`app/pages/admin/catalog.vue`): таблица номенклатуры с поиском и пагинацией.
* **Шаблоны КП** (`app/pages/admin/proposal-templates.vue`): загрузка, правка названия/даты (PATCH) и удаление; ошибки показываются на странице, а не `alert`/`console`.
* **Manager** (`app/pages/manager/specifications.vue`): Загрузка спецификаций + SSE-лог обработки.
* **Middleware** (`app/middleware/auth-guard.global.ts`): глобальный, защищает роуты `/admin/*` и `/manager/*` по роли из `/auth/me`. Работает на клиенте (куки ставит backend на своём origin, SSR их не видит) — настоящий контроль ролей остаётся на backend (`require_role`).
* **Smoke-тест:** сборка Nuxt — 2.16 MB (548 kB gzip), все роуты доступны; эндпоинты: admin — 200, manager на `/admin/*` — 403, гость — 401; блокировка устройства → вход с него 403, после разблокировки — 204; отзыв сессии уменьшает список и повторяет 404.
* **Осталось в рамках задачи:** редактирование каталога (backend отдаёт только чтение), интерфейс подтверждения колонок прайс-листа, виртуальный скролл таблицы спецификаций и действия менеджера (выбрать из ТОП-N / исключить / подтвердить) с записью в `HistoricalMatch` — эндпоинты на backend есть, в UI не подключены.


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
  * ✅ Страница `/admin/proposal-templates`: форма загрузки, таблица, удаление, подсветка действующего шаблона.
  * ⚠️ `PATCH` реализован на backend, в UI редактирование названия/даты не подключено.

### Задача 7.2: Сборка и экспорт документа

* **Требования к AI:**
* Эндпоинт `GET /api/v1/manager/specifications/{id}/export?format=pdf|xlsx`.
* Джоин подтвержденных `SpecificationRow` (количество) с `CatalogItem` (цена, артикул). Расчет сумм и НДС.
* Генерация PDF (через `weasyprint` + HTML шаблон Jinja2), сохранение в MinIO, скачивание в браузере пользователя.


* **DoD:** Менеджер получает оформленный файл коммерческого предложения по клику на кнопку в UI.
