"""One error format for every endpoint: {"code", "message", "retryable"}; messages are in Russian."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False, headers: dict | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.retryable, self.headers = status, code, message, retryable, headers


def bad_request(code: str, message: str) -> ApiError:
    return ApiError(400, code, message)


def unauthorized(message: str = "Нужна авторизация") -> ApiError:
    return ApiError(401, "unauthorized", message)


def forbidden(code: str = "forbidden", message: str = "Недостаточно прав") -> ApiError:
    return ApiError(403, code, message)


def not_found(code: str = "not_found", message: str = "Не найдено") -> ApiError:
    return ApiError(404, code, message)


def conflict(code: str, message: str) -> ApiError:
    return ApiError(409, code, message)


def unavailable(code: str, message: str) -> ApiError:
    return ApiError(503, code, message, retryable=True)


def _body(code: str, message: str, retryable: bool) -> dict:
    return {"code": code, "message": message, "retryable": retryable}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError) -> JSONResponse:
        return JSONResponse(_body(e.code, e.message, e.retryable), status_code=e.status, headers=e.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError) -> JSONResponse:
        first = e.errors()[0] if e.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", []) if x not in ("body", "query", "path"))
        msg = f"Некорректный запрос: {where} — {first.get('msg', 'ошибка')}" if where else "Некорректный запрос"
        return JSONResponse(_body("validation_error", msg, False), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(e.status_code, "http_error")
        return JSONResponse(_body(code, str(e.detail), e.status_code >= 500), status_code=e.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, e: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse(_body("internal_error", "Внутренняя ошибка сервиса", True), status_code=500)
