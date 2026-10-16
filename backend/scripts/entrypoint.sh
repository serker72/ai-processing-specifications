#!/bin/sh
# Entrypoint-обёртка: экспорт модели (если настроен) + основной процесс контейнера.
set -e

/app/scripts/export_model.sh || {
  echo ">>> export_model.sh завершился с ошибкой — контейнер не стартует (fail-fast)" >&2
  exit 1
}

exec "$@"
