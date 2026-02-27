from fastapi import APIRouter, Query
from typing import Any, Dict
import requests
from config import get_clusters, get_prometheus_token

router = APIRouter(prefix="/api/observe", tags=["observe"])


def _prom_request(cluster_name: str, path: str, params: dict) -> dict:
    clusters = get_clusters()
    cluster = clusters.get(cluster_name)
    if not cluster:
        return {"ok": False, "error": f"Cluster bulunamadı: {cluster_name}", "result": []}
    prom_url = cluster.get("prometheus_url", "").rstrip("/")
    if not prom_url:
        return {"ok": False, "error": f"{cluster_name} için prometheus_url tanımlanmamış", "result": []}
    token = get_prometheus_token(cluster_name)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        resp = requests.get(
            f"{prom_url}{path}",
            headers=headers,
            params=params,
            timeout=20,
            verify=False,
        )
        resp.raise_for_status()
        data = resp.json()
        return {"ok": True, "result": data.get("data", {}).get("result", [])}
    except Exception as e:
        return {"ok": False, "error": str(e), "result": []}


# ── Instant query ─────────────────────────────────────────────────────────────

@router.post("/promql")
def run_promql(body: Dict[str, Any]) -> Dict[str, Any]:
    """Prometheus instant query. body: {cluster, query, time?}"""
    cluster = body.get("cluster", "").strip()
    query = body.get("query", "").strip()
    if not cluster:
        return {"ok": False, "error": "cluster boş", "result": []}
    if not query:
        return {"ok": False, "error": "Sorgu boş", "result": []}
    params: Dict[str, Any] = {"query": query}
    if body.get("time"):
        params["time"] = body["time"]
    return _prom_request(cluster, "/api/v1/query", params)


# ── Range query ───────────────────────────────────────────────────────────────

@router.post("/promql/range")
def run_promql_range(body: Dict[str, Any]) -> Dict[str, Any]:
    """Prometheus range query. body: {cluster, query, start, end, step}"""
    cluster = body.get("cluster", "").strip()
    query = body.get("query", "").strip()
    if not cluster:
        return {"ok": False, "error": "cluster boş", "result": []}
    if not query:
        return {"ok": False, "error": "Sorgu boş", "result": []}
    params: Dict[str, Any] = {"query": query}
    for k in ("start", "end", "step"):
        if body.get(k):
            params[k] = body[k]
    return _prom_request(cluster, "/api/v1/query_range", params)


# ── Label helpers ─────────────────────────────────────────────────────────────

@router.get("/promql/labels")
def list_labels(cluster: str = Query(...)) -> Dict[str, Any]:
    """Prometheus'taki tüm label adlarını döner."""
    return _prom_request(cluster, "/api/v1/labels", {})


@router.get("/promql/label-values")
def list_label_values(cluster: str = Query(...), label: str = Query(...)) -> Dict[str, Any]:
    """Belirtilen label'ın tüm değerlerini döner."""
    return _prom_request(cluster, f"/api/v1/label/{label}/values", {})
