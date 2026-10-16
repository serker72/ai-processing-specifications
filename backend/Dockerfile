FROM python:3.13-slim

# Системные зависимости для weasyprint (pango/cairo)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Установка uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# --- Флаг процессора для выбора бэкенда эмбеддинга при экспорте -------------
# IS_INTEL_CPU=true только на x86_64 с GenuineIntel (OpenVINO оптимизирован под Intel).
RUN if [ "$(uname -m)" = "x86_64" ] && grep -q "GenuineIntel" /proc/cpuinfo 2>/dev/null; then \
      echo "IS_INTEL_CPU=true" > /app/.env_build; \
    else \
      echo "IS_INTEL_CPU=false" > /app/.env_build; \
    fi

# --- Зависимости -------------------------------------------------------------
# ARG WORKER_CUDA_VISIBLE_DEVICES: непустое значение → CUDA-сборка PyTorch,
# пустое (по умолчанию) → CPU-сборка (uv.lock содержит CPU-индекс pytorch-cpu).
ARG WORKER_CUDA_VISIBLE_DEVICES=""

# Кэширование зависимостей: сначала только файлы зависимостей
COPY pyproject.toml uv.lock ./

# Venv вне /app, чтобы bind-mount исходников его не затирал
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

# Базовая установка (CPU torch из uv.lock) + extras группы intel (openvino,
# optimum-intel) — нужны для OpenVINO-экспорта и инференса на CPU.
RUN uv sync --frozen --no-dev --no-install-project --extra intel

# Если передан WORKER_CUDA_VISIBLE_DEVICES — заменяем torch на CUDA-сборку
RUN if [ -n "${WORKER_CUDA_VISIBLE_DEVICES}" ]; then \
      uv pip install --python /opt/venv/bin/python \
        --index-url https://download.pytorch.org/whl/cu124 \
        torch; \
    fi

COPY app ./app

# Файлы миграций Alembic (DSN берётся из окружения, alembic.ini не содержит секретов)
COPY alembic.ini ./
COPY alembic ./alembic

# Скрипты для экспорта модели и entrypoint
COPY scripts/ ./scripts/
RUN chmod +x ./scripts/*.sh

EXPOSE 8000

ENV PATH="/opt/venv/bin:$PATH"

# Ограничение потоков математических вычислений (OpenMP/MKL/BLAS) — CPU-режим
ENV OMP_NUM_THREADS=4 \
    MKL_NUM_THREADS=4 \
    OPENBLAS_NUM_THREADS=4 \
    NUMEXPR_NUM_THREADS=4

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
