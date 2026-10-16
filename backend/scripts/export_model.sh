#!/usr/bin/env bash
# Экспорт модели эмбеддингов в ONNX/OpenVINO для CPU-инференса.
#
# Чтение флагов из /app/.env_build (задаётся в Dockerfile на этапе сборки).
# Переменные окружения:
#   EMBEDDING_MODEL_NAME  — имя модели HF (по умолчанию intfloat/multilingual-e5-base)
#   EMBEDDING_MODEL_CACHE_DIR  — каталог, куда записываются экспортированные файлы
#   EMBEDDING_DEVICE    — «cuda» пропуск экспорта (PyTorch на GPU не нужен)
set -euo pipefail

echo ">>> export_model.sh: старт"

# --- флаги сборки -----------------------------------------------------------
ENV_BUILD="/app/.env_build"
IS_INTEL_CPU="false"
if [ -f "$ENV_BUILD" ]; then
  IS_INTEL_CPU="$(grep -E '^IS_INTEL_CPU=' "$ENV_BUILD" | cut -d= -f2)"
fi

# --- параметры из окружения --------------------------------------------------
MODEL_NAME="${EMBEDDING_MODEL_NAME:-intfloat/multilingual-e5-base}"
CACHE_DIR="${EMBEDDING_MODEL_CACHE_DIR:-}"
DEVICE="${EMBEDDING_DEVICE:-cpu}"

# Если каталог кэша не задан — выключено
if [ -z "$CACHE_DIR" ]; then
  echo ">>> EMBEDDING_MODEL_CACHE_DIR не задан — экспорт пропущен"
  exit 0
fi

# Если GPU — пропускать за ненадобностью
if [ "$DEVICE" = "cuda" ]; then
  echo ">>> EMBEDDING_DEVICE=cuda — экспорт пропущен (GPU работает через нативный PyTorch)"
  exit 0
fi

# --- уже экспортирована? ----------------------------------------------------
if ls "$CACHE_DIR"/*.onnx >/dev/null 2>&1 || ls "$CACHE_DIR"/openvino*.xml >/dev/null 2>&1; then
  echo ">>> Модель уже экспортирована в $CACHE_DIR — пропуск"
  exit 0
fi

mkdir -p "$CACHE_DIR"

# --- подготовка: копируем метаданные HF-снапшота (токенизер, конфиг) --------
# Исключаем бинарные веса (safetensors/pt), они не нужны для ONNX/OpenVINO.
SNAPSHOT_DIR="$(python -c "from huggingface_hub import snapshot_download; print(snapshot_download('$MODEL_NAME'))")"
echo ">>> HF-снапшот: $SNAPSHOT_DIR"

# Копируем текстовые файлы (конфиг, токенизер) без весов
cp -L "$SNAPSHOT_DIR"/config.json "$CACHE_DIR/" 2>/dev/null || true
cp -L "$SNAPSHOT_DIR"/tokenizer.json "$CACHE_DIR/" 2>/dev/null || true
cp -L "$SNAPSHOT_DIR"/tokenizer_config.json "$CACHE_DIR/" 2>/dev/null || true
cp -L "$SNAPSHOT_DIR"/special_tokens_map.json "$CACHE_DIR/" 2>/dev/null || true
cp -L "$SNAPSHOT_DIR"/sentence_bert_config.json "$CACHE_DIR/" 2>/dev/null || true
cp -L "$SNAPSHOT_DIR"/modules.json "$CACHE_DIR/" 2>/dev/null || true
cp -L "$SNAPSHOT_DIR"/vocab.txt "$CACHE_DIR/" 2>/dev/null || true
cp -L "$SNAPSHOT_DIR"/merges.txt "$CACHE_DIR/" 2>/dev/null || true
cp -L "$SNAPSHOT_DIR"/1_Pooling/config.json "$CACHE_DIR/" 2>/dev/null || true

# --- выбор бэкенда ----------------------------------------------------------
TARGET_DIR="$(mktemp -d)"

if [ "$IS_INTEL_CPU" = "true" ] && python -c "import openvino" 2>/dev/null; then
  echo ">>> Экспорт в OpenVINO (IS_INTEL_CPU=true, openvino доступен)"
  optimum-cli export openvino --model "$MODEL_NAME" --task feature-extraction "$TARGET_DIR"
  BACKEND_NAME="OpenVINO"
else
  echo ">>> Экспорт в ONNX (Intel не обнаружен или openvino недоступен)"
  optimum-cli export onnx --model "$MODEL_NAME" --task feature-extraction "$TARGET_DIR"
  BACKEND_NAME="ONNX"
fi

# --- объединяем: метаданные + экспортированная модель -----------------------
cp -L "$TARGET_DIR"/* "$CACHE_DIR/" 2>/dev/null || true
rm -rf "$TARGET_DIR"

echo ">>> Экспорт $BACKEND_NAME завершён: $CACHE_DIR"
ls -la "$CACHE_DIR" | grep -E '\.(onnx|xml|json|txt|txt)$' || true

echo ">>> export_model.sh: завершено успешно"
