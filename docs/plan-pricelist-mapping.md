# План работ: прайс-маппинг (P0-остаток), P1, P2

> План сохранён для продолжения в другой сессии. Дата фиксации: 2026-09-14.
> Коммиты-основа: `c373848` (Backend P0), `11085e3` (Frontend кабинет), `664ec11` (Docs).
> Контейнеры остановлены (`docker compose down`), данные в томах сохранены.
>
> Файл содержит три плана: текущий (UI подтверждения маппинга прайс-листов),
> P1 (надёжность realtime и рабочее место менеджера) и P2 (экспорт КП и эксплуатация).

## Статус выполнения (сверка с кодом 2026-09-30)

- **P0 (UI маппинга прайс-листов)** — шаги 1–9 ✅ ПОЛНОСТЬЮ. Шаг 9 (smoke в docker
  compose) пройден 2026-09-30: прайс-лист (10 позиций) загружен → LLM-маппинг →
  confirm → worker `catalog.vectorize` → статус `completed` → позиции SKU001–SKU010
  появились в `/admin/catalog`; спецификация (6 строк) загружена менеджером →
  worker `specification.process` → статус `completed` → все 6 строк `matched` в
  `/manager/specifications/{id}/rows`. При smoke найден и исправлен дефект
  `MinioService` (см. «Дефекты, найденные при smoke»).
- **P1** — шаги 1–6 и 8 ✅ (реализованы 2026-10-01), шаг 7 (тесты) отложен по решению
  команды («тестов пока нет»). Сделано: буфер SSE в Redis (`LPUSH/LTRIM`+TTL,
  воспроизведение при подписке, дедупликация по `seq`); `PATCH .../rows/{row_id}` и
  `GET .../matches`; рабочий стол `manager/specifications/[uploadId].vue`; устойчивый SSE
  (`composables/useSpecStream.ts` с backoff + `$authRefresh`, применён и в
  `specifications/index.vue`); fail-fast конфиг (`JWT_SECRET_KEY`/`JWT_COOKIE_SECURE` вне
  `loc`, предупреждение о несовпадении CORS-домена). Проверка: `ruff check app/` и
  `npm run build` — успешно; docker-compose smoke пройден 2026-10-01 (см. ниже).
- **P2** — шаг 3 ✅ (сделан ранее в `11085e3`); шаг 5 частично (`/api/v1/health` есть,
  healthcheck backend/worker в compose нет); шаги 1, 2, 4, 6, 7 — не начаты.
  Для шага 1: `weasyprint` в `pyproject.toml` есть, **`jinja2` нет** — добавить.
- **Расхождение в документации:** `KODA.md` указывает `GET /health`, фактический маршрут —
  `/api/v1/health` (`main.py`, `api_prefix + "/health"`); исправить при ближайшей правке.

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
   ✅ smoke в docker compose пройден 2026-09-30: загрузка прайса (`.xlsx`, 10 строк) →
   preview → confirm → история (статусы mapping_predicted→processing→completed) →
   позиции SKU001–SKU010 в `/admin/catalog`; загрузка спецификации менеджером (6 строк) →
   worker → статус completed → 6 строк `matched` в `/manager/specifications/{id}/rows`.

## Дефекты, найденные при smoke (исправлены 2026-09-30)

- **`MinioService` переиспользовал клиент между event loop воркера.** Celery-таска
  (`_run_async`) создаёт новый `asyncio` loop для каждой таски и закрывает его, а
  `MinioService` — process-Singleton с ленивым aioboto3-клиентом: клиент, созданный в
  loop первой таски (`catalog.vectorize`), переиспользовался во второй
  (`specification.process`) и падал с `Event loop is closed` (aiohttp-коннектор
  привязан к закрытому loop). Фикс: клиент переключается по `id(running_loop)` — при
  смене loop старый клиент сбрасывается без `await` (loop мёртв) и создаётся новый
  (`_client_loop` + `_reset_client` в `minio_service.py`). Требует пересборки
  `docker compose build backend` и `--force-recreate worker`.
- **`Unclosed client session/connector` в логах воркера (исправлено 2026-10-01).** После
  сброса старого MinIO-клиента при смене loop его aiohttp-сессия оставалась открытой, и
  при `loop.close()` aiohttp писал предупреждение. Фикс: `MinioService.close()` /
  `close_all()` закрывают aioboto3-контекст текущего loop, а `_run_async` в `tasks.py`
  вызывает `close_all()` в `finally`, пока loop ещё жив. Код монтируется volume'ом —
  достаточно `docker compose restart worker` (проверено: две подряд таски, лог чистый).

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

1. ✅ **Backend: надёжный SSE.** ГОТОВО: `RedisPubSub.publish(..., buffered=True)` кладёт
   событие в Redis LIST `{channel}:events` (`LPUSH`+`LTRIM` до 2000+`EXPIRE` 1 ч);
   `buffered_events(channel)` отдаёт буфер в хронологическом порядке; `GET .../stream`
   сначала подписывается, затем воспроизводит буфер, отсекая дубли по `seq`.
2. ✅ **Backend: действия над строками.** ГОТОВО: `PATCH /api/v1/manager/specifications/{upload_id}/rows/{row_id}`
   (`RowStatusUpdateRequest` → `SpecificationService.update_row_status`): статус
   `confirmed`/`excluded`, для confirmed — `catalog_item_id` (или уже сопоставленная
   позиция), проверка владельца `get_for_manager`, запись в `HistoricalMatch` через
   `MatchingService.confirm_match`.
3. ✅ **Backend: варианты для строки.** ГОТОВО: `GET .../rows/{row_id}/matches`
   (`limit` 1–20) → `SpecificationService.get_row_matches` поверх `MatchingService.match_row`
   (top-N кандидатов векторного поиска + текущая позиция).
4. ✅ **Frontend: рабочий стол менеджера** `app/pages/manager/specifications/[uploadId].vue`:
   таблица строк с пагинацией, цветовая кодировка `match_type`/`status`, диалог подтверждения
   (текущая позиция или ТОП-N кандидатов), исключение через PATCH, сводка `rows_by_status`.
   Виртуальный скролл не понадобился: пагинация по 50 строк.
5. ✅ **Frontend: устойчивый SSE.** ГОТОВО: `app/composables/useSpecStream.ts` —
   переподключение с экспоненциальным backoff (до 15 с), перед реконнектом `$authRefresh`
   (экспортирован из `plugins/api.ts`), закрытие потока на `completed`/`error`,
   дедупликация по `seq`. Применён в `specifications/[uploadId].vue` и
   `specifications/index.vue` (голый `new EventSource` убран).
6. ✅ **Backend: fail-fast конфиг.** ГОТОВО: `Settings._validate_safety` — вне
   `PROJECT_ENVIRONMENT=loc` запрещает дефолтный `JWT_SECRET_KEY` и `JWT_COOKIE_SECURE=False`;
   `_warn_cors_domain_mismatch` предупреждает, если ни один origin CORS не совпадает с
   доменом `BACKEND_BASE_URL`. Сообщения — в `ConfigMessages`.
7. ⏸ **Тесты (pytest, backend/tests)** — отложены по решению команды (тестов в проекте пока нет).
8. ✅ **Проверка:** `ruff check app/` — чисто; `npm run build` — успешно. Docker-compose smoke
   пройден 2026-10-01: каталог наполнен 3 позициями (SKU001–003, эмбеддинги e5), менеджер
   загрузил спецификацию (3 строки) → обработка `completed` → **подключение к SSE уже после
   завершения отдало все 5 событий буфера (seq 1–5), включая первые строки** (дефект потери
   событий закрыт) → `GET .../matches` вернул кандидатов → `PATCH` подтвердил одну строку
   (`confirmed`) и исключил другую (`excluded`), сводка `matched:1, confirmed:1, excluded:1` →
   повторная загрузка того же файла дала `match_type=auto` (Tier-1) для подтверждённого
   наименования. Логи воркера чистые: `Unclosed client session/connector` устранены
   (см. «Дефекты, найденные при smoke»).

# План P2: функциональное расширение и эксплуатация

> После P1. Порядок внутри — по ценности, можно брать частями.

## Шаги

1. **Экспорт КП (задача 7.2, ключевая недостающая функция).** Разбит на подпункты
   P2.1.1–P2.1.7 (ниже). Решения зафиксированы 2026-10-02.

   **Зафиксированные решения:**
   - **Состав КП:** строки в статусах `confirmed` и `matched` (у `matched` позиция
     каталога всегда есть); `excluded` / `pending` / `unmatched` не включаются.
   - **Цена:** из `CatalogItem.price` (не из цены в файле клиента). Пустое `quantity`
     → строка исключается. Если включённых строк нет → `400`.
   - **НДС:** ставка и флаг «выделять НДС из цены» — в таблице системных настроек
     (одна запись, правит админ). Ставка — `20.00` (проценты).
     Состав колонок таблицы КП **одинаков** в обоих режимах: `Цена`, `Сумма`.
     Итоговые строки внизу:
     * «Итого» — сумма по строкам (Кол-во × Цена);
     * `vat_included=true` → «В том числе НДС {vat_rate}%» = Итого × vat_rate/(100+vat_rate);
       `vat_included=false` → «Без НДС» (сумма в «Итого» указана без НДС);
     * «Всего» — итог к оплате: при `vat_included=true` = Итого, при `vat_included=false`
       = Итого + НДС.
   - **Настройки (singleton):** реквизиты продавца (наименование, ИНН, КПП, юр. адрес,
     телефон, email, р/с, банк, БИК, к/с, подписант — ФИО, должность) + `vat_rate`,
     `vat_included`.
   - **Клиенты:** наименование, ИНН, адрес, контактное лицо, email — обязательны;
     телефон — необязателен. Менеджеры видят всех клиентов, но изменяют только своих;
     админы видят всех и изменяют любых.
   - **PDF:** WeasyPrint + Jinja2; сначала загруженный шаблон
     (`ProposalTemplateService.get_current_template`), если нет — встроенный дефолтный
     с условными блоками (`{% if vat_included %}`). Контекст фиксируется и документируется.
   - **Хранение КП:** `proposals` (номер, дата, `user_id`, `client_id`, `upload_id`) +
     `proposal_documents` (версии файлов: `file_key`, `format`, `rows_fingerprint`).
     Нумерация `КП-{год}-{5 цифр}`, глобальная, сброс раз в год.
   - **Скачивание:** формируется при первом запросе, повторные клики отдают готовый файл.
     «Сформировать повторно» — номер тот же, новый файл добавляется в историю документов,
     старый остаётся.
   - **Контроль изменений строк:** `rows_fingerprint` (SHA-256 канонического JSON
     включённых строк) сравнивается при открытии рабочего стола; при расхождении UI
     показывает «Данные изменились» и предлагает переформировать.
   - **XLSX** в этой итерации не реализуется.
   - **История КП:** менеджер видит только свои; страница `/manager/proposals`.
   - **Очистка спецификаций:** существующие `specification_uploads` (smoke-данные) удалить,
     `client_id` сделать обязательным.

   **Подпункты:**
   - ✅ **P2.1.1** Backend: системные настройки — таблица `app_settings` (singleton), миграция
     `c1a2b3d4e5f6`, репозиторий/сервис, `GET/PATCH /api/v1/admin/settings`.
   - ✅ **P2.1.2** Backend: клиенты — таблица `clients`, миграция `d2b3c4e5f6a7`,
     репозиторий/сервис, `GET/POST /api/v1/manager/clients`,
     `PATCH /api/v1/manager/clients/{id}` (только свои), `GET/PATCH /api/v1/admin/clients`.
   - ✅ **P2.1.3** Backend: очистка спецификаций, `client_id` (NOT NULL) в
     `specification_uploads` (миграция `e3c4d5f6a7b8`), приём `client_id` при загрузке
     спецификации (`POST /manager/specifications`).
   - ✅ **P2.1.4** Backend: генерация PDF КП — `proposals` + `proposal_documents` +
     `proposal_counters` (миграция `f4d5e6a7b8c9`); встроенный шаблон с условными
     блоками; WeasyPrint; MinIO; эндпоинты формирования/скачивания/повторного
     формирования/истории.
   - ✅ **P2.1.5** Frontend: страница настроек в админке (`/admin/settings`).
   - ✅ **P2.1.6** Frontend: выбор/создание клиента при загрузке спецификации.
   - ✅ **P2.1.7** Frontend: панель формирования/скачивания КП на рабочем столе
     (`manager/specifications/[uploadId].vue`), страница истории `/manager/proposals`,
     пункт меню «Коммерческие предложения».
   - ✅ **P2.1.8** Проверка: `ruff check app/` — чисто; `npm run build` — успешно;
     smoke в docker compose пройден 2026-10-02 (см. «Smoke P2.1» ниже).

   **Дефекты, найденные при smoke P2.1 (исправлены 2026-10-02):**
   - **Enum `tp_row_status` без `processing`/`unmatched`.** Enum создавался по ранней
     версии `RowStatus`, а позже в модели появились `processing`/`unmatched` без
     миграции. Воркер Matching Engine пишет `unmatched` → обработка спецификаций падала
     (`InvalidTextRepresentation`). Исправлено миграцией `a5e6f7b8c9d0`
     (`ALTER TYPE ... ADD VALUE IF NOT EXISTS`, в `autocommit_block`).
   - **Устаревший счётчик документов КП в ответе сразу после формирования.**
     `selectinload` возвращал identity-mapped `Proposal` с закэшированной пустой
     коллекцией `documents`, поэтому POST отдавал `documents_count: 0`. Исправлено
     `execution_options(populate_existing=True)` в `get_by_id`/`get_by_upload`
     (`proposal_repository.py`).

   **Smoke P2.1 (2026-10-02):** миграции `c1a2b3d4e5f6`→`a5e6f7b8c9d0` применены;
   `GET/PATCH /admin/settings` (реквизиты + НДС) работают; `GET/POST/PATCH
   /manager/clients` и `GET /admin/clients` работают; `POST
   /manager/specifications` валидирует `client_id` (400 при неизвестном, 422 без
   поля); КП по спецификации сформировано (`КП-2026-00001`), PDF скачивается
   (`application/pdf`, `%PDF-`), `force=true` добавляет версию под тем же номером
   (docs 1→2→3→4); смена статуса строки переключает `needs_regeneration=true`;
   режимы НДС (`vat_included=false/true`) отдают PDF. Логи backend без ошибок.
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
