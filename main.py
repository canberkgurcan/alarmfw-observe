from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import clusters, resources, metrics

app = FastAPI(title="AlarmFW Observe", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(clusters.router)
app.include_router(resources.router)
app.include_router(metrics.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
