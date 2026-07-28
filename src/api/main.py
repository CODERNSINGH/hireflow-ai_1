"""
HireFlow AI — FastAPI Application Entrypoint

Start the development server:
    uvicorn src.api.main:app --reload

Browse the interactive docs:
    http://localhost:8000/docs
"""

from fastapi import FastAPI

from src.api.routes.profile import router as profile_router
from src.api.routes.weekly_plan import router as weekly_plan_router
from src.api.routes.applications import router as applications_router
from src.api.routes.reports import router as reports_router

app = FastAPI(
    title="HireFlow AI API",
    description=(
        "Career autopilot for students. "
        "Discovers jobs, tailors resumes, applies automatically, "
        "and generates personalised prep guides."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# --------------------------------------------------------------------------- #
# Routers
# --------------------------------------------------------------------------- #

app.include_router(profile_router)
app.include_router(weekly_plan_router)
app.include_router(applications_router)
app.include_router(reports_router)

# --------------------------------------------------------------------------- #
# Health check
# --------------------------------------------------------------------------- #


@app.get("/", tags=["health"])
def health_check() -> dict:
    """Basic liveness probe.

    Returns a simple JSON object confirming the API is running.
    Useful for Docker health checks and load-balancer probes.
    """
    return {"status": "ok", "service": "hireflow-api"}
