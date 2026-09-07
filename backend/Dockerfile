FROM python:3.13-slim

# Системные зависимости для weasyprint (pango/cairo)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Установка uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Кэширование зависимостей: сначала только файлы зависимостей
COPY pyproject.toml uv.lock ./

# Venv вне /app, чтобы bind-mount исходников его не затирал
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app

# Файлы миграций Alembic (DSN берётся из окружения, alembic.ini не содержит секретов)
COPY alembic.ini ./
COPY alembic ./alembic

EXPOSE 8000

ENV PATH="/opt/venv/bin:$PATH"

# Ограничение потоков математических вычислений (OpenMP/MKL/BLAS) — CPU-режим
ENV OMP_NUM_THREADS=4 \
    MKL_NUM_THREADS=4 \
    OPENBLAS_NUM_THREADS=4 \
    NUMEXPR_NUM_THREADS=4

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
