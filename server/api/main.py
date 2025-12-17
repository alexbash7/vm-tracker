from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import engine, Base
from routers import ingest, machines, activity

# Создаём таблицы
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Activity Tracker API",
    description="API для сбора и анализа активности пользователей",
    version="1.0.0"
)

# CORS для dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене указать конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Роутеры
app.include_router(ingest.router)
app.include_router(machines.router)
app.include_router(activity.router)


@app.get("/")
async def root():
    return {"status": "ok", "service": "activity-tracker-api"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
