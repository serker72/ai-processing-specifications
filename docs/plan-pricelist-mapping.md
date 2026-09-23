# План работ: прайс-маппинг (P0-остаток), P1, P2

> План сохранён для продолжения в другой сессии. Дата фиксации: 2026-09-14.
> Коммиты-основа: `c373848` (Backend P0), `11085e3` (Frontend кабинет), `664ec11` (Docs).
> Контейнеры остановлены (`docker compose down`), данные в томах сохранены.
>
> Файл содержит три плана: текущий (UI подтверждения маппинга прайс-листов),
> P1 (надёжность realtime и рабочее место менеджера) и P2 (экспорт КП и эксплуатация).

## Контекст

P0 закрыт: каталог наполняется (`vectorize_catalog` из confirm + UPSERT по `(sku,name)`),
`process_specification` коммитит по батчам и пишет статусы `UploadStatus`,
у менеджера есть `GET /manager/specifications`, `/{id}`, `/{id}/rows` с проверкой владельца.

Осталась задача 3.x из design-plan: **интерфейс подтверждения колонок прайс-листа** —
админ видит историю загрузок со статусами, открывает превью файла, правит/подтверждает
маппинг (4 роли + доп. колонки), после confirm запускается векторизация каталога.

## Ключевые факты о коде (проверено)

- `PriceListUpload`: JSONB `column_mapping` (ключи `sku_column`, `name_column`,
  `price_column`, `unit_column`, `additional_columns`), статус `UploadStatus`
  (`pending / mapping_predicted / processing / completed / failed`).
  Колонок `sheet_name` / `mapping_confidence` / `deleted_at` в схеме **нет** — не добавлять.
- `ExcelPreviewService.read_preview(fileobj, max_rows)` → `{sheets, headers, rows, total_rows}`;
  `max_rows=None` читает весь лист (используется в `parse_pricelist`).
- `MinioService.download_fileobj(key)` → BytesIO.
- `confirm_mapping` в `price_list_service.py` уже пишет `unit_column` и ставит
  `UploadStatus.processing`; эндпоинт `POST /admin/pricelists/{id}/confirm` уже делает
  `commit_upload()` + `vectorize_catalog.delay(upload_id)`.
- Схемы: `app/schemas/confirm_mapping.py` (`ConfirmMappingRequest` с `unit_column`,
  `ConfirmMappingResponse`), `app/schemas/price_list.py` (`PriceListUploadItem`,
  `PriceListListResponse`).
- Frontend: Nuxt 3, авто-импорты; API-клиент `$api` (`app/plugins/api.ts`);
  стили `.status-badge.mapping_predicted/.processing/.completed/.failed` уже есть в
  `app/assets/css/main.css`. Каталогов `frontend/shared`, `endpoints.ts`, тест-раннера нет —
  помощники класть в `app/utils/` (авто-импорт), проверка сборкой `npm run build`.
- Кэша эмбеддингов в backend нет (`core/cache` отсутствует) — шаг инвалидации кэша не нужен.
- LLM: локальная Ollama (`host.docker.internal:11434`, `ollama/qwen2.5:7b`) — при smoke
  предсказание маппинга работает.

## Шаги

1. ✅ **Backend: GET /api/v1/admin/pricelists — фильтр по статусу и счётчики статусов**
   (репозиторий/сервис/схема/эндпоинт). ГОТОВО: `list_filtered(status)` + `count_by_status()`
   в `price_list_repository.py`; `status`/`counts` в сервисе и `PriceListListResponse`;
   query-параметр `status` в эндпоинте `list_pricelists` (`app/api/v1/admin.py`).
2. ✅ **Backend: GET /api/v1/admin/pricelists/{upload_id}/preview** — ГОТОВО:
   `PriceListService.get_preview(upload_id)` (файл из MinIO через `download_fileobj`,
   превью 50 строк через `ExcelPreviewService`, исходное имя файла через
   `StoredFileKey.original_name`, `FileNotFoundError`/`ValueError` для эндпоинта) +
   эндпоинт в `admin.py` (400 для невалидного UUID, 404 если загрузки нет).
3. ✅ **Backend: POST /api/v1/admin/pricelists/{upload_id}/confirm** — ГОТОВО:
   перед записью маппинга читаются заголовки файла из MinIO
   (`ExcelPreviewService.read_headers`), отсутствующая `sku_column`/`name_column`
   → 400 (`PriceListMessages.column_not_in_file`), невалидный UUID → 400,
   несуществующая загрузка → 404 (`UPLOAD_NOT_FOUND`); далее как раньше —
   `commit_upload()` + `vectorize_catalog.delay()`.
4. ✅ **Backend: Pydantic-схема `PriceListPreviewResponse`** (sheets/headers/rows/total_rows/
   column_mapping/status) в `app/schemas/price_list.py` — УЖЕ БЫЛА в коде до шага 2
   (проверено, реализацию в схеме не дублировать). Confirm переиспользует
   `ConfirmMappingRequest/Response`.
5. ✅ **Backend: миграция** — ГОТОВО: `b7d41f2a9c33` — индекс
   `ix_price_list_uploads_status_created_at` (`status`, `created_at DESC`) в модели
   `PriceListUpload.__table_args__` и в миграции (с `op.f(...)`), откат в downgrade.
   Применение — `docker compose exec backend alembic upgrade head` (после
   `docker compose build backend`: каталог `alembic/` копируется в образ).
6. ✅ **Frontend: `app/utils/pricelist.ts`** — ГОТОВО: `MAPPING_ROLES` (sku/name/price/unit),
   `ADDITIONAL_ROLE`, `assignmentsFromMapping`, `buildMappingPayload`, `countMappedColumns`,
   `isMappingComplete`.
7. ✅ **Frontend: `app/pages/admin/pricelists/index.vue`** — ГОТОВО (перенесена из
   `pricelists.vue`): фильтр-чипы по статусу со счётчиками, кнопка «Маппинг» для строк в
   статусах `mapping_predicted` / `failed` (ссылка на `/admin/pricelists/[uploadId]`).
8. ✅ **Frontend: `app/pages/admin/pricelists/[uploadId].vue`** — ГОТОВО: редактор ролей
   (колонка → роль / «не использовать» / доп. колонка со свободной ролью, примеры значений),
   основная роль у одной колонки (повторное назначение снимает её с прежней), таблица превью
   с подписями ролей; «Подтвердить маппинг» активна при назначенных SKU и наименовании и
   только в статусах `mapping_predicted` / `failed` (иначе режим просмотра);
   `POST .../confirm` → редирект в историю. Стили `.preview-scroll`, `.mapping-input`.
9. **Проверка**: ✅ `ruff check` изменённых файлов; ✅ `npm run build` во frontend;
   ⏳ smoke в docker compose: загрузка прайса → preview → confirm → история (статусы
   processing→completed) → позиции в `/admin/catalog`; загрузка спецификации менеджером →
   строки в `/manager/uploads`.

## Окружение / команды

- Стек: FastAPI + dishka, Celery worker, pgvector/pg17 через pgbouncer, Redis, MinIO,
  Nuxt 3, nginx. Запуск: `docker compose up -d` из корня; миграции —
  `docker compose exec backend alembic upgrade head` (миграции лежат в
  `backend/alembic/versions/`, каталога `backend/backend` не существует).
- Backend-venv: `backend/.venv` (Python 3.13, ruff, pytest настроен, тестов пока нет).
- Smoke-пользователи создавались скриптом через `docker compose exec backend python`
  (bcrypt-хэш через `SecurityService`); email вида `...@example.com` — pydantic
  отклоняет `.test.local` как email.
- Рабочий каталог инструментов — корень репозитория `/home/serg/projects/ai-processing-specifications`;
  файловые инструменты иногда резолвят пути от `backend/` (см. предупреждение в KODA.md).

---

# План P1: надёжность realtime и рабочее место менеджера

> Выполняется сразу после плана «UI подтверждения маппинга прайс-листов» (шаги 1–9 выше).

## Контекст / известные дефекты (проверено по коду)

- **SSE теряет события**: frontend подписывается на `GET .../stream` только *после* ответа
  `POST /manager/specifications`, а таска уже публикует в Redis Pub/Sub — события до
  подписки безвозвратно потеряны (Pub/Sub без backlog).
- **EventSource вне `$api`**: `new EventSource(...)` в `manager/specifications.vue` не
  проходит через интерцептор 401→refresh (`plugins/api.ts`) — при истёкшем access-токене
  поток молча умирает.
- **Нет действий менеджера над строками**: в `RowStatus` есть `confirmed`/`excluded`, но
  **эндпоинта смены статуса строки не существует** (проверено grep по `app/` — есть только
  `POST /manager/match/confirm`, который пишет в `HistoricalMatch`, но не трогает
  `SpecificationRow`). Рабочий стол менеджера (остаток задачи 6.2) нереализуем без backend.
- **Конфиг не валидируется на старте**: `JWT_SECRET_KEY` имеет дефолт
  `change-me-in-production` (`config.py:107`), `JWT_COOKIE_SECURE=False` — в prod можно
  незаметно подняться с небезопасными куками; `CORS_ORIGINS` не сверяется с
  `NUXT_PUBLIC_API_BASE` (риск: куки backend не считаются same-site для origin фронтенда).
- **Тестов нет**: pytest настроен в `pyproject.toml`, каталога `tests/` нет.

## Шаги

1. **Backend: надёжный SSE.** Буфер последних событий на загрузку в Redis
   (`LIST spec:{id}:events`, `LPUSH`+`LTRIM`, TTL ~1 ч) в `RedisPubSub.publish`;
   `GET .../stream` при подписке отдаёт буфер (`LRANGE`) до перехода на live-подписку.
   Альтернатива (проще): переносить `process_specification.delay()` на момент после
   первого подключения SSE — отвергнуто, обработка не должна зависеть от открытой вкладки.
2. **Backend: действия над строками.** `PATCH /api/v1/manager/specifications/{upload_id}/rows/{row_id}`
   — статус `confirmed`/`excluded` + (для confirmed) `catalog_item_id`; проверка владельца
   через `get_for_manager`; подтверждение дополнительно пишет в `HistoricalMatch`
   (Tier-1 словарь) — переиспользовать `MatchingService.confirm_match`.
3. **Backend: варианты для строки.** `GET /api/v1/manager/specifications/{upload_id}/rows/{row_id}/matches`
   — топ-N кандидатов векторного поиска по `raw_name` строки (для UI «выбрать из ТОП-N»).
4. **Frontend: рабочий стол менеджера** `app/pages/manager/specifications/[uploadId].vue`:
   таблица строк из `GET .../rows` с пагинацией, цветовое кодирование по `match_type`
   (auto/top_n/unmatched), действия «Подтвердить» (выбор позиции из ТОП-N или совпавшей),
   «Исключить» → PATCH из шага 2; сводка из `GET .../{upload_id}` (`rows_by_status`).
   Виртуальный скролл при >500 строк (лёгкая собственная реализация, без новых зависимостей).
5. **Frontend: устойчивый SSE.** Обёртка над EventSource: переподключение с backoff,
   перед реконнектом `refreshOnce()` из `plugins/api.ts`; при `status=completed/error` —
   закрытие потока и обновление списка/сводки.
6. **Backend: fail-fast конфиг.** В `Settings` (или startup-hook `main.py`): запрет
   дефолтного `JWT_SECRET_KEY` и `JWT_COOKIE_SECURE=False` при `environment != "loc"`;
   предупреждение, если origin из `CORS_ORIGINS` не совпадает с доменом `BACKEND_BASE_URL`.
7. **Тесты (pytest, backend/tests):** `ExcelPreviewService.read_preview`,
   `PriceListService.parse_pricelist`/`_to_float`, `CatalogRepository.upsert_batch`
   (ON CONFLICT), `SpecificationService._as_number`, tiers `MatchingService` (мок repo/embedder),
   auth-поток (401/403, refresh-ротация) на httpx ASGI-транспорте с мок-Redis/MinIO.
8. **Проверка:** ruff + pytest; docker compose smoke: upload спецификации → SSE-лог не
   теряет первые строки (буфер) → подтверждение/исключение строк → повторная загрузка
   того же наименования матчится Tier-1 (`auto`).

# План P2: функциональное расширение и эксплуатация

> После P1. Порядок внутри — по ценности, можно брать частями.

## Шаги

1. **Экспорт КП (задача 7.2, ключевая недостающая функция).**
   `GET /api/v1/manager/specifications/{upload_id}/export?format=pdf|xlsx`:
   джоин `SpecificationRow` (confirmed, quantity) × `CatalogItem` (price, sku, unit),
   суммы и НДС; PDF — WeasyPrint + Jinja2 по текущему шаблону
   (`ProposalTemplateService.get_current_template`), XLSX — openpyxl; файл в MinIO
   (`exports/…`) + отдача браузеру. Зависимости: `weasyprint`, `jinja2` (проверить, что
   системные libs WeasyPrint ставятся в backend-образ Dockerfile).
   Frontend: кнопка «Скачать КП» на рабочем столе менеджера.
2. **Редактирование каталога (админ).** Сейчас `GET /admin/catalog` read-only:
   `PATCH /api/v1/admin/catalog/{item_id}` (price, unit, name) + форма на
   `pages/admin/catalog.vue`. Правки цены не пересоздают эмбеддинг (он по наименованию).
3. ✅ **UI шаблонов КП: редактирование.** УЖЕ РЕАЛИЗОВАНО в `11085e3`: инлайн-правка
   (`startEdit`/`saveTemplate`) → `PATCH /admin/proposal-templates/{id}` на
   `pages/admin/proposal-templates.vue`.
4. **Повторная обработка упавших загрузок.** Кнопка «Повторить» для `failed` в истории
   прайсов и спецификаций: `POST .../pricelists/{id}/retry` и `.../specifications/{id}/retry`
   (пере-постановка таски с существующим `column_mapping`).
5. **Наблюдаемость.** Healthcheck-эндпоинт уже есть (`/api/v1/health`) — добавить
   healthcheck-и контейнеров backend/worker в `docker-compose.yml`; структурированные
   логи worker (upload_id в каждой записи); счётчик `failed`-загрузок в истории админки.
6. **UX-полировка.** Пагинация истории прайсов (сейчас грузится всё), авто-обновление
   статусов в истории (polling 5 с для строк в `processing`), тосты вместо текстовых
   `error`-блоков, скелетоны таблиц при загрузке.
7. **Безопасность (остатки).** Ротация `JWT_SECRET_KEY` без обрыва сессий не требуется
   (сессии в Redis), но: вынести `JWT_COOKIE_SECURE`/`JWT_COOKIE_DOMAIN` в чеклист
   прод-развёртывания в README; рассмотреть `SameSite=Lax`→`Strict` для refresh-куки
   после проверки, что refresh не вызывается кросс-сайтово.
