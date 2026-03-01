from fastapi import APIRouter, Query
from typing import Any, Dict
import requests
from config import (
    get_global_prometheus_url,
    get_global_prometheus_token,
    get_global_prometheus_timeout_sec,
    get_global_prometheus_verify_tls,
)

router = APIRouter(prefix="/api/observe", tags=["observe"])


def _prom_request(path: str, params: dict) -> dict:
    prom_url = get_global_prometheus_url().rstrip("/")
    if not prom_url:
        return {"ok": False, "error": "Prometheus URL tanımlanmamış (PROMETHEUS_URL env veya observe.yaml global.prometheus_url)", "result": []}
    token = get_global_prometheus_token()
    if not token:
        return {"ok": False, "error": "Prometheus token bulunamadı — Secrets sayfasından prometheus.token ekleyin", "result": []}
    headers = {"Authorization": f"Bearer {token}"}
    timeout_sec = get_global_prometheus_timeout_sec()
    verify_tls = get_global_prometheus_verify_tls()
    try:
        resp = requests.get(
            f"{prom_url}{path}",
            headers=headers,
            params=params,
            timeout=timeout_sec,
            verify=verify_tls,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            return {"ok": False, "error": data.get("error") or "Prometheus returned non-success status", "result": []}
        return {"ok": True, "result": data.get("data", {}).get("result", [])}
    except Exception as e:
        return {"ok": False, "error": str(e), "result": []}


# ── Instant query ─────────────────────────────────────────────────────────────

@router.post("/promql")
def run_promql(body: Dict[str, Any]) -> Dict[str, Any]:
    """Prometheus instant query. body: {query, time?}  (cluster artık global'dir, görmezden gelinir)"""
    query = body.get("query", "").strip()
    if not query:
        return {"ok": False, "error": "Sorgu boş", "result": []}
    params: Dict[str, Any] = {"query": query}
    if body.get("time"):
        params["time"] = body["time"]
    return _prom_request("/api/v1/query", params)


# ── Range query ───────────────────────────────────────────────────────────────

@router.post("/promql/range")
def run_promql_range(body: Dict[str, Any]) -> Dict[str, Any]:
    """Prometheus range query. body: {query, start, end, step}"""
    query = body.get("query", "").strip()
    if not query:
        return {"ok": False, "error": "Sorgu boş", "result": []}
    params: Dict[str, Any] = {"query": query}
    for k in ("start", "end", "step"):
        if body.get(k):
            params[k] = body[k]
    return _prom_request("/api/v1/query_range", params)


# ── Label helpers ─────────────────────────────────────────────────────────────

@router.get("/promql/labels")
def list_labels() -> Dict[str, Any]:
    """Prometheus'taki tüm label adlarını döner."""
    return _prom_request("/api/v1/labels", {})


@router.get("/promql/label-values")
def list_label_values(label: str = Query(...)) -> Dict[str, Any]:
    """Belirtilen label'ın tüm değerlerini döner."""
    return _prom_request(f"/api/v1/label/{label}/values", {})


# ── Alerts ────────────────────────────────────────────────────────────────────

@router.get("/alerts")
def get_alerts() -> Dict[str, Any]:
    """Prometheus'tan şu an firing olan alert listesi."""
    return _prom_request("/api/v1/query", {"query": 'ALERTS{alertstate="firing"}'})


# ── Pod Metrics ───────────────────────────────────────────────────────────────

@router.get("/pod-metrics")
def get_pod_metrics(
    pod:       str = Query(...),
    namespace: str = Query(...),
) -> Dict[str, Any]:
    """Pod başına container CPU (rate 5m, cores) ve Memory (working set, bytes)."""
    cpu = _prom_request("/api/v1/query", {
        "query": (
            f'sum(rate(container_cpu_usage_seconds_total{{'
            f'pod="{pod}",namespace="{namespace}",'
            f'container!="",container!="POD"}}[5m])) by (container)'
        ),
    })
    mem = _prom_request("/api/v1/query", {
        "query": (
            f'sum(container_memory_working_set_bytes{{'
            f'pod="{pod}",namespace="{namespace}",'
            f'container!="",container!="POD"}}) by (container)'
        ),
    })
    return {"cpu": cpu, "memory": mem}
