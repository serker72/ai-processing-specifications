"""Сервис эмбеддингов: локальная модель sentence-transformers (Singleton).

Модель загружается один раз при первом обращении (ленивая инициализация) и
переиспользуется всем приложением. Для multilingual-e5 перед текстом обязателен
префикс ("query: " / "passage: ").
"""

import threading
from typing import ClassVar, Self

from sentence_transformers import SentenceTransformer

from app.core.config import Settings


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
                    self._model = SentenceTransformer(
                        self._settings.embedding.model_name,
                        device=self._settings.embedding.device,
                    )
        return self._model

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
