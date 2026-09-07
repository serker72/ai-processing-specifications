"""Сервис LLM: единый слой доступа к моделям через litellm.

Роутинг провайдера задаётся настройками (LLM_PROVIDER):
- 'openai' — облачная модель (OPENAI_API_KEY), по умолчанию gpt-4o-mini;
- 'ollama' — локальная модель Ollama (LLM_OLLAMA_BASE_URL).

Переключение не требует изменений кода — только переменных окружения.
"""

import json
from typing import Any

import litellm

from app.core.config import LlmSettings, Settings


class LlmService:
    """Обёртка над litellm: completion и structured output для задач анализа."""

    def __init__(self, settings: Settings) -> None:
        self._llm_settings: LlmSettings = settings.llm
        litellm.drop_params = True  # не падать на параметрах, не поддерживаемых провайдером

    def _model_name(self) -> str:
        """Имя модели в формате litellm в зависимости от активного провайдера."""
        s = self._llm_settings
        if s.provider == "ollama":
            return s.ollama_model
        return s.openai_model

    def _api_base(self) -> str | None:
        """Базовый URL для локальных провайдеров (Ollama); для облака — None."""
        if self._llm_settings.provider == "ollama":
            return self._llm_settings.ollama_base_url
        return None

    def _completion_kwargs(self) -> dict[str, Any]:
        """Общие параметры запроса (модель, temperature, timeout, api_base)."""
        return {
            "model": self._model_name(),
            "api_base": self._api_base(),
            "temperature": self._llm_settings.temperature,
            "max_tokens": self._llm_settings.max_tokens,
            "timeout": self._llm_settings.request_timeout,
        }

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Простой запрос: вернуть текст ответа модели."""
        response = await litellm.acompletion(
            **self._completion_kwargs(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return str(response.choices[0].message.content or "")

    async def complete_json(self, system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Запрос со структурированным ответом (JSON по заданной схеме).

        Используется режим response_format=json_object (поддерживается и OpenAI,
        и Ollama), сама JSON Schema передаётся в системном промпте. Схема —
        JSON Schema без внешнего ключа "json_schema".
        """
        schema_json = json.dumps(schema, ensure_ascii=False)
        response = await litellm.acompletion(
            **self._completion_kwargs(),
            messages=[
                {"role": "system", "content": f"{system_prompt}\n\nОтвет строго в формате JSON по схеме:\n{schema_json}"},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        content = str(response.choices[0].message.content or "{}")
        return json.loads(content)
