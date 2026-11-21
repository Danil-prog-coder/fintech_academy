import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, retryable: bool = False):
        self.code, self.message, self.status, self.retryable = code, message, status, retryable


def _body(code: str, message: str, retryable: bool) -> dict:
    return {"code": code, "message": message, "retryable": retryable}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(_body(exc.code, exc.message, exc.retryable), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        return JSONResponse(
            _body("validation_error", "Некорректные данные запроса.", False), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return JSONResponse(_body("http_error", "Ошибка запроса.", False), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        # Только тип исключения: тексты запросов в логи не попадают.
        log.error("unhandled error: %s", type(exc).__name__)
        return JSONResponse(
            _body("internal_error", "Внутренняя ошибка сервера.", True), status_code=500
        )
