from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import APP_ENV, CORS_ORIGINS
from app.database import (
    check_database_connection,
    create_db_and_tables,
)
from app.errors import (
    http_exception_handler,
    validation_exception_handler,
)
from app.middleware import RequestIdMiddleware
from app.routers import (
    assistant,
    chat,
    documents,
    jobs,
    knowledge_base_documents,
    knowledge_bases,
    organizations,
    rag,
    service_catalog,
    service_requests,
    todos,
    users,
)
from app.runtime_health import check_broker_connection

app = FastAPI()
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
app.add_middleware(RequestIdMiddleware)
app.add_exception_handler(
    StarletteHTTPException,
    http_exception_handler,
)
app.add_exception_handler(
    RequestValidationError,
    validation_exception_handler,
)

app.include_router(rag.router)


@app.on_event("startup")
def on_startup():
    if APP_ENV == "development":
        create_db_and_tables()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/live")
def liveness():
    return {"status": "alive"}


@app.get("/health/ready")
def readiness():
    try:
        check_database_connection()
    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="database is not ready",
        )

    try:
        check_broker_connection()
    except RedisError:
        raise HTTPException(
            status_code=503,
            detail="task broker is not ready",
        )

    return {"status": "ready"}


app.include_router(users.router)
app.include_router(organizations.router)
app.include_router(jobs.router)
app.include_router(knowledge_bases.router)
app.include_router(knowledge_base_documents.router)
app.include_router(service_catalog.router)
app.include_router(service_requests.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(todos.router)
app.include_router(assistant.router)
