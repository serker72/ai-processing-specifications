"""Единый реестр пользовательских сообщений приложения.

Все тексты сообщений (ошибки API, статусы, логи) собраны в этом модуле;
в коде используются только ссылки на константы. Группировка — по доменам:
один класс на модуль системы. Для сообщений с параметрами — статические
методы, возвращающие отформатированную строку.
"""


class CommonMessages:
    """Общие сообщения."""

    INTERNAL_ERROR = "Внутренняя ошибка сервера"
    VALIDATION_ERROR = "Ошибка валидации данных"
    NOT_FOUND = "Объект не найден"
    FORBIDDEN = "Доступ запрещён"
    FILE_TOO_LARGE = "Файл слишком большой (максимальный размер — 50 МБ)"


class AuthMessages:
    """Сообщения модуля авторизации."""

    INVALID_CREDENTIALS = "Неверный email или пароль"
    FINGERPRINT_MISMATCH = "Fingerprint не совпадает"
    SESSION_NOT_FOUND = "Сессия не найдена или отозвана"
    INVALID_TOKEN = "Невалидный токен"
    TOKEN_MISSING = "Токен отсутствует"
    REFRESH_TOKEN_MISSING = "Refresh-токен отсутствует"
    TOKEN_REVOKED = "Токен отозван"
    USER_NOT_FOUND = "Пользователь не найден"
    DEVICE_BLOCKED = "Вход с этого устройства заблокирован"


class UserMessages:
    """Сообщения управления пользователями (панель администратора)."""

    ROLE_SELF_CHANGE = "Нельзя изменить собственную роль"


class PriceListMessages:
    """Сообщения модуля прайс-листов."""

    UPLOAD_NOT_FOUND = "Загрузка прайс-листа не найдена"

    @staticmethod
    def column_not_in_file(column: str) -> str:
        return f"Колонка «{column}» не найдена в файле прайс-листа"


class SpecificationMessages:
    """Сообщения модуля спецификаций."""

    ROW_NOT_FOUND = "Строка спецификации не найдена"
    ROW_STATUS_UNSUPPORTED = "Недопустимый статус строки"
    CONFIRM_REQUIRES_ITEM = "Для подтверждения строки нужна позиция каталога"
    CATALOG_ITEM_NOT_FOUND = "Позиция каталога не найдена"


class ConfigMessages:
    """Сообщения валидации конфигурации на старте приложения."""

    @staticmethod
    def default_secret_in_non_loc(environment: str) -> str:
        return (
            f"JWT_SECRET_KEY имеет небезопасное значение по умолчанию при "
            f"PROJECT_ENVIRONMENT={environment!r}: задайте собственный секрет"
        )

    @staticmethod
    def insecure_cookies_in_non_loc(environment: str) -> str:
        return (
            f"JWT_COOKIE_SECURE=False при PROJECT_ENVIRONMENT={environment!r}: "
            f"auth-куки должны передаваться только по HTTPS"
        )

    @staticmethod
    def cors_domain_mismatch(origins: list[str], domain: str) -> str:
        return (
            f"Ни один origin из CORS_ORIGINS не совпадает с доменом BACKEND_BASE_URL "
            f"({domain}): {origins}. Проверьте same-site для auth-кук"
        )
