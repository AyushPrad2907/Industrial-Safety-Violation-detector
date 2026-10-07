import os
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import database
from backend.api.routes import router as api_router
from backend.api.websocket import router as ws_router
from backend.services.monitoring_service import monitoring_service

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for startup and shutdown."""
    # 1. Initialize SQLite Database
    database.init_db()
    # 2. Bind current async event loop to MonitoringService for thread-safe WebSocket broadcasts
    loop = asyncio.get_running_loop()
    monitoring_service.set_async_loop(loop)
    # 3. Pre-load AI models safely
    monitoring_service.initialize_models()
    logger.info("FastAPI Industrial Safety Violation Detector Backend started.")
    yield
    # Shutdown
    monitoring_service.stop_monitoring()
    logger.info("FastAPI backend stopped cleanly.")

# Create FastAPI application
app = FastAPI(
    title="Industrial Safety Violation Detector API",
    description="Backend API for Real-Time PPE Compliance, Temporal Decision Engine, and Safety Monitoring.",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS specifically for development frontend origins (e.g., Vite standard ports)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(api_router)
app.include_router(ws_router)
