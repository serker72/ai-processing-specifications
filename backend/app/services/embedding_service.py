"""Сервис эмбеддингов: локальная модель sentence-transformers (Singleton).

Модель загружается один раз при первом обращении (ленивая инициализация) и
переиспользуется всем приложением. Для multilingual-e5 перед текстом обязателен
префикс ("query: " / "passage: ").

Выбор бэкенда:
- GPU (EMBEDDING_DEVICE=cuda) → PyTorch напрямую;
- CPU + EMBEDDING_MODEL_CACHE_DIR с openvino_model.xml → OpenVINO;
- CPU + EMBEDDING_MODEL_CACHE_DIR с model.onnx → ONNX;
- иначе → PyTorch CPU.
"""

import logging
import threading
from pathlib import Path
from typing import ClassVar, Self

from sentence_transformers import SentenceTransformer

from app.core.config import Settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Генерация эмбеддингов локальной моделью (один экземпляр на процесс)."""

    QUERY_PREFIX = "query: "
    PASSAGE_PREFIX = "passage: "

    _instances: ClassVar[dict[str, "EmbeddingService"]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __new__(cls, settings: Settings) -> Self:
        """Singleton: один экземпляр сервиса на процесс (ключ — имя модели)."""
        key = settings.embedding.model_name
        with cls._lock:
            if key not in cls._instances:
                instance = super().__new__(cls)
                instance._init(settings)
                cls._instances[key] = instance
        return cls._instances[key]

    def _init(self, settings: Settings) -> None:
        """Инициализация состояния (вызывается один раз из __new__)."""
        self._settings = settings
        self._model: SentenceTransformer | None = None
        self._model_lock = threading.Lock()

    @property
    def model(self) -> SentenceTransformer:
        """Ленивая загрузка модели: тяжёлая инициализация при первом обращении."""
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    self._model = self._load_model()
        return self._model

    def _load_model(self) -> SentenceTransformer:
        """Загрузка модели с учётом устройства и экспортированных бэкендов."""
        emb = self._settings.embedding
        device = emb.device
        cache_dir = Path(emb.model_cache_dir) if emb.model_cache_dir else None

        if "cuda" in device:
            logger.info("EmbeddingService: GPU (device=%s), PyTorch backend", device)
            return SentenceTransformer(emb.model_name, device=device)

        # CPU: проверяем экспортированные форматы в EMBEDDING_MODEL_CACHE_DIR
        if cache_dir is not None and cache_dir.is_dir():
            ov_files = list(cache_dir.glob("openvino*.xml"))
            onnx_files = list(cache_dir.glob("*.onnx"))
            if ov_files:
                logger.info("EmbeddingService: OpenVINO backend (%s)", ov_files[0])
                return SentenceTransformer(str(cache_dir), device="cpu", backend="openvino")
            if onnx_files:
                logger.info("EmbeddingService: ONNX backend (%s)", onnx_files[0])
                return SentenceTransformer(str(cache_dir), device="cpu", backend="onnx")
            logger.info(
                "EmbeddingService: EMBEDDING_MODEL_CACHE_DIR=%s — ONNX/OpenVINO файлы не найдены, PyTorch CPU",
                cache_dir,
            )

        logger.info("EmbeddingService: PyTorch CPU (model=%s)", emb.model_name)
        return SentenceTransformer(emb.model_name, device=device)

    def warm_up(self) -> None:
        """Прогреть модель (загрузить в память) — вызывается при старте воркера/приложения."""
        _ = self.model

    def embed_query(self, text: str) -> list[float]:
        """Эмбеддинг поискового запроса (строки спецификации)."""
        return self.model.encode(
            f"{self.QUERY_PREFIX}{text.strip()}",
            normalize_embeddings=True,
        ).tolist()

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """Эмбеддинги документов каталога (прайс-лист) — батчево."""
        if not texts:
            return []
        prepared = [f"{self.PASSAGE_PREFIX}{t.strip()}" for t in texts]
        embeddings = self.model.encode(prepared, batch_size=64, normalize_embeddings=True)
        return embeddings.tolist()
