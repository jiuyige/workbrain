from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.middleware import REQUEST_ID_HEADER

STATUS_CODE_TO_ERROR_CODE = {
    400: "BAD_REQUEST",
    401: "AUTHENTICATION_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    502: "UPSTREAM_SERVICE_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def get_request_id(request: Request) -> str:
    return request.state.request_id


def build_error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = get_request_id(request)
    response_headers = dict(headers or {})
    response_headers[REQUEST_ID_HEADER] = request_id

    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "request_id": request_id,
        },
        headers=response_headers,
    )


async def http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    code = STATUS_CODE_TO_ERROR_CODE.get(
        exc.status_code,
        "HTTP_ERROR",
    )

    if isinstance(exc.detail, str):
        message = exc.detail
    else:
        message = "request failed"

    return build_error_response(
        request,
        status_code=exc.status_code,
        code=code,
        message=message,
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return build_error_response(
        request,
        status_code=422,
        code="VALIDATION_ERROR",
        message="request validation failed",
    )
