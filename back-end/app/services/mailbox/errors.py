from app.core.errors import AppError


def unavailable() -> AppError:
    return AppError(
        "mail_unavailable", "Почтовый сервер недоступен, попробуйте позже.", 502, retryable=True
    )


def server_unavailable(kind: str, host: str, port: int) -> AppError:
    """Как unavailable(), но называет сервер: видно, какой из двух не отвечает."""
    return AppError(
        "mail_unavailable",
        f"Не удалось подключиться к {kind}-серверу {host}:{port}. Попробуйте позже.",
        502,
        retryable=True,
    )


def auth_failed() -> AppError:
    return AppError(
        "mail_auth_failed",
        "Почтовый сервер отклонил логин или пароль. "
        "Для Gmail, Яндекса и Mail.ru нужен пароль приложения, а не основной пароль.",
        400,
    )


def rejected() -> AppError:
    return AppError("mail_rejected", "Почтовый сервер отклонил запрос.", 502)


def folder_not_found() -> AppError:
    return AppError("folder_not_found", "Папка не найдена.", 404)


def message_not_found() -> AppError:
    return AppError("message_not_found", "Письмо не найдено.", 404)
