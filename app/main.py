from fastapi import FastAPI

from app.database import create_db_and_tables
from app.routers import assistant, chat, documents, todos, users

from app.routers import rag

app = FastAPI()

app.include_router(rag.router)



@app.on_event("startup")
def on_startup():
    create_db_and_tables()


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(users.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(todos.router)
app.include_router(assistant.router)