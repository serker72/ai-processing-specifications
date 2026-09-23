# Руководство для контрибьюторов

Подробный контекст (архитектура, модели, конфигурация) — в `KODA.md`; требования — в `docs/design-plan.md`. При расхождении плана и кода приоритет у кода.

## Структура проекта

- `backend/` — FastAPI (Python ≥ 3.13, uv). Код в `backend/app/`: `api/v1/` (роутеры), `services/` (бизнес-логика), `repositories/` (SQL), `models/models.py` (все ORM-модели), `schemas/`, `di/` (dishka), `worker/` (Celery), `core/config.py`, `core/messages.py`. Миграции — `backend/alembic/versions/`.
- `frontend/` — Nuxt 3 + Tailwind v4, `srcDir: app/` (`pages/`, `layouts/`, `composables/`, `plugins/`, `middleware/`).
- `srv/` — конфиги nginx и pgbouncer; `docs/` — планы; `docker-compose.yml` — все сервисы.
- `backend/` и `frontend/` — соседние каталоги: указывайте пути от корня репозитория.

## Сборка, запуск и проверка

```bash
docker compose build backend frontend && docker compose up -d   # из корня, нужен .env (шаблон .env.example)
docker compose restart backend        # правки backend/app подхватываются без пересборки
docker compose build backend          # после изменений pyproject.toml, uv.lock, alembic/
docker compose build frontend         # после любых правок фронтенда
```

В `backend/`: `uv sync`, `uv run ruff check .`, `uv run pytest`, `uv run alembic upgrade head`.
В `frontend/` (Node через NVM, добавьте его bin в `PATH`): `npm ci --legacy-peer-deps`, `npm run dev`, `npm run build`.

## Стиль кода и правила

- ruff: `line-length = 100`, `target-version = py313`; `X | None`, `Mapped[...]`/`mapped_column`.
- Код и идентификаторы — на английском, комментарии и docstrings — на русском.
- Слои: обработчик → сервис (класс) → репозиторий. Зависимости через dishka: `route_class=DishkaRoute`, `FromDishka[...]`.
- Пользовательские тексты — только в `app/core/messages.py` (`AuthMessages`, `CommonMessages`, …).
- Долгие операции (парсинг, эмбеддинги, матчинг) — в Celery-тасках.
- Миграции — вручную по скиллу `alembic-create-revision`: `uv run alembic revision -m "..."`, без autogenerate, одна таблица на миграцию, Enum-типы `tp_*`.
- Frontend: цвета только из токенов темы (`bg-app-*`, `var(--app-*)`), без хардкода hex; `.nuxt/`, `.output/`, `node_modules/` не коммитить.

## Тестирование

pytest (dev-зависимость); каталог `backend/tests/` ещё не создан — новые тесты размещать там, файлы `test_*.py`. К новой функциональности добавляйте тесты. У фронтенда тестов нет: проверка — успешный `npm run build`.

## Коммиты и пулл-реквесты

- Формат: `<Область>: <краткое описание на русском>`, области — `Backend`, `Frontend`, `Infra`, `Docs`. Пример: `Backend: фоновая обработка спецификаций и SSE-прогресс (Задача 5.2)`.
- Ссылайтесь на номер задачи из `docs/design-plan.md`, если он есть.
- В PR: описание изменений, затронутые сервисы, нужна ли пересборка образов/миграции, скриншоты для UI-изменений.

## Безопасность

`.env` не коммитить — новые переменные добавлять в `.env.example` и в соответствующую группу `config.py`. JWT выдаются только через HttpOnly-cookie.
