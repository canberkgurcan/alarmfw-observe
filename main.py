import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import clusters, resources, metrics

app = FastAPI(title="AlarmFW Observe", version="0.1.0")


def _load_allow_origins() -> list[str]:
    """
    Comma-separated origins via ALLOW_ORIGINS.
    Secure-by-default to local UI origins if env is missing/empty.
    """
    raw = os.getenv("ALLOW_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").strip()
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins or ["http://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_load_allow_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(clusters.router)
app.include_router(resources.router)
app.include_router(metrics.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
