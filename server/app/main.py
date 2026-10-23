"""TradeTrack API entrypoint.

On startup: ensure the tt_* tables exist (additive, never destructive), then optionally seed demo
data. Run with:  uvicorn app.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import seed
from app.config import settings
from app.database import ensure_schema
from app.routers import billing, config, inbound, receipts, users

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_schema()
    await seed.run()  # no-op unless development or ZZPAY_SEED_DEMO=true
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,  # the auth cookie must be sent cross-origin in dev
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config.router)
app.include_router(users.router)
app.include_router(receipts.router)
app.include_router(billing.router)
app.include_router(inbound.router)
