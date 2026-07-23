import json
import logging
from time import perf_counter
from uuid import UUID, uuid4

from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"
request_logger = logging.getLogger("workbrain.request")
request_logger.setLevel(logging.INFO)
request_logger.propagate = False

if not request_logger.handlers:
    request_log_handler = logging.StreamHandler()
    request_log_handler.setFormatter(logging.Formatter("%(message)s"))
    request_logger.addHandler(request_log_handler)


def resolve_request_id(header_value: str | None) -> str:
    if header_value is not None:
        try:
            return str(UUID(header_value))
        except ValueError:
            pass

    return str(uuid4())


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        started_at = perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            self._log_request(
                request=request,
                request_id=request_id,
                status_code=500,
                started_at=started_at,
                exception=True,
            )
            raise

        response.headers[REQUEST_ID_HEADER] = request_id
        self._log_request(
            request=request,
            request_id=request_id,
            status_code=response.status_code,
            started_at=started_at,
        )

        return response

    @staticmethod
    def _log_request(
        *,
        request: Request,
        request_id: str,
        status_code: int,
        started_at: float,
        exception: bool = False,
    ) -> None:
        event = json.dumps(
            {
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": round(
                    (perf_counter() - started_at) * 1000,
                    3,
                ),
            },
            separators=(",", ":"),
        )

        if exception:
            request_logger.exception(event)
        else:
            request_logger.info(event)
