from fastapi import APIRouter, Query
from typing import Any, Dict, List
from concurrent.futures import ThreadPoolExecutor

from routers.metrics import _prom_request

router = APIRouter(prefix="/api/observe/health", tags=["health"])


# ── Helpers ────────────────────────────────────────────────────────────────────

def _scalar(res: dict) -> int:
    """Extract a count/scalar value from a Prometheus vector result.
    Returns -1 when the query itself failed (Prometheus unreachable, bad query, etc.)
    so callers can distinguish 'error' from 'genuinely zero'.
    """
    if not res.get("ok"):
        return -1
    results = res.get("result", [])
    if not results:
        return 0
    val = results[0].get("value", [None, "0"])
    try:
        return int(float(val[1]))
    except (TypeError, ValueError, IndexError):
        return len(results)


def _par(queries: Dict[str, str], cluster: str, timeout: int = 25) -> Dict[str, dict]:
    """Run multiple PromQL instant queries in parallel, return raw results keyed by name."""
    with ThreadPoolExecutor(max_workers=min(len(queries), 10)) as pool:
        futures = {
            k: pool.submit(_prom_request, "/api/v1/query", {"query": q}, cluster)
            for k, q in queries.items()
        }
        return {k: fut.result(timeout=timeout) for k, fut in futures.items()}


def _rows(res: dict) -> List[dict]:
    return res.get("result", []) if res.get("ok") else []


def _par_result(raw: Dict[str, dict]) -> Dict[str, Any]:
    """Build a detail-endpoint response from parallel query results.
    Includes an 'errors' map so callers know which queries failed vs. returned empty data.
    """
    errors = {k: v.get("error", "query failed") for k, v in raw.items() if not v.get("ok")}
    data   = {k: _rows(v) for k, v in raw.items()}
    return {"ok": True, "errors": errors, **data}


# ── Overview (30s polling) ─────────────────────────────────────────────────────

@router.get("/overview")
def health_overview(cluster: str = Query("")) -> Dict[str, Any]:
    """All cluster health counts in a single call. Poll at 30 s."""
    queries = {
        "firing_alerts":           'count(ALERTS{alertstate="firing"}) or vector(0)',
        "crashloop":               'count(kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"} > 0) or vector(0)',
        "oomkilled":               'count(kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} > 0) or vector(0)',
        "imagepull":               'count(kube_pod_container_status_waiting_reason{reason=~"ImagePullBackOff|ErrImagePull"} > 0) or vector(0)',
        "pending_pods":            'count(kube_pod_status_phase{phase="Pending"} == 1) or vector(0)',
        "notready_nodes":          'count(kube_node_status_condition{condition="Ready",status!="true"} == 1) or vector(0)',
        "unavailable_deployments": 'count(kube_deployment_status_replicas_unavailable > 0) or vector(0)',
        "failed_jobs":             'count(kube_job_status_failed > 0) or vector(0)',
    }
    raw = _par(queries, cluster)
    counts = {}
    for k, res in raw.items():
        try:
            counts[k] = _scalar(res)
        except Exception:
            counts[k] = -1
    return {"ok": True, "cluster": cluster, **counts}


# ── Enhanced Alerts (15s polling) ─────────────────────────────────────────────

_SEV_ORDER = {"critical": 0, "warning": 1, "error": 2, "info": 3}


@router.get("/alerts")
def health_alerts(cluster: str = Query("")) -> Dict[str, Any]:
    """Firing alerts enriched with active duration in seconds."""
    raw = _par({
        "alerts":   'ALERTS{alertstate="firing"}',
        "duration": 'time() - ALERTS_FOR_STATE{alertstate="firing"}',
    }, cluster)

    alerts_res   = raw["alerts"]
    duration_res = raw["duration"]

    if not alerts_res.get("ok"):
        return {"ok": False, "error": alerts_res.get("error", ""), "result": []}

    # Build duration map keyed by alertname|namespace
    dur_map: Dict[str, float] = {}
    for r in _rows(duration_res):
        m   = r.get("metric", {})
        key = f"{m.get('alertname', '')}|{m.get('namespace', '')}"
        val = r.get("value", [None, None])[1]
        try:
            dur_map[key] = float(val)
        except (TypeError, ValueError):
            pass

    enriched = []
    for r in _rows(alerts_res):
        m   = r.get("metric", {})
        key = f"{m.get('alertname', '')}|{m.get('namespace', '')}"
        enriched.append({
            "metric":      m,
            "value":       r.get("value"),
            "active_secs": dur_map.get(key),
        })

    enriched.sort(key=lambda x: (
        _SEV_ORDER.get((x["metric"].get("severity") or "").lower(), 9),
        -(x["active_secs"] or 0),
    ))

    return {"ok": True, "result": enriched}


# ── Nodes (15s polling) ────────────────────────────────────────────────────────

@router.get("/nodes")
def health_nodes(cluster: str = Query("")) -> Dict[str, Any]:
    """Node health: NotReady, pressure conditions, CPU/memory/disk usage."""
    queries = {
        "notready": 'kube_node_status_condition{condition="Ready",status!="true"} == 1',
        "pressure": 'kube_node_status_condition{condition=~"MemoryPressure|DiskPressure|PIDPressure",status="true"} == 1',
        "cpu":      'topk(30, 100 - avg by(node) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)',
        "memory":   'topk(30, (node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100)',
        "disk":     'topk(30, (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100)',
    }
    raw = _par(queries, cluster)
    return _par_result(raw)


# ── Workload Issues (15s polling) ─────────────────────────────────────────────

@router.get("/workload")
def health_workload(cluster: str = Query("")) -> Dict[str, Any]:
    """Workload problems: CrashLoop, OOMKilled, ImagePull, Pending pods, Unavailable deployments, Failed jobs."""
    queries = {
        "crashloop":   'topk(50, kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"} > 0)',
        "oomkilled":   'topk(50, kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} > 0)',
        "imagepull":   'topk(50, kube_pod_container_status_waiting_reason{reason=~"ImagePullBackOff|ErrImagePull"} > 0)',
        "pending":     'topk(50, kube_pod_status_phase{phase="Pending"} == 1)',
        "unavailable": 'topk(20, kube_deployment_status_replicas_unavailable > 0)',
        "failed_jobs": 'topk(20, kube_job_status_failed > 0)',
    }
    raw = _par(queries, cluster)
    return _par_result(raw)


# ── Capacity (15s polling) ────────────────────────────────────────────────────

@router.get("/capacity")
def health_capacity(cluster: str = Query("")) -> Dict[str, Any]:
    """Capacity: CPU usage/request ratio, ResourceQuota usage, PVC fill level."""
    queries = {
        # CPU usage ÷ request per namespace (cores used / cores requested)
        "cpu_ratio": (
            'topk(20, '
            '  sum by(namespace) (rate(container_cpu_usage_seconds_total{container!="",container!="POD"}[5m])) '
            '/ ignoring(resource) '
            '  sum by(namespace) (kube_pod_container_resource_requests{resource="cpu",container!="",container!="POD"}) '
            '> 0)'
        ),
        "quota_used": 'kube_resourcequota{type="used"} > 0',
        "quota_hard": 'kube_resourcequota{type="hard"} > 0',
        "pvc_ratio":  'topk(20, kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes > 0.5)',
        # Absolute CPU usage per namespace (for namespaces without requests)
        "cpu_abs": (
            'topk(20, '
            '  sum by(namespace) (rate(container_cpu_usage_seconds_total{container!="",container!="POD"}[5m])) > 0)'
        ),
    }
    raw = _par(queries, cluster)
    return _par_result(raw)


# ── Control Plane (15s polling) ───────────────────────────────────────────────

@router.get("/controlplane")
def health_controlplane(cluster: str = Query("")) -> Dict[str, Any]:
    """Control plane: etcd health, API server error rate & latency, certificate expiry."""
    queries = {
        "etcd_db_size":       "etcd_mvcc_db_total_size_in_bytes",
        "etcd_has_leader":    "etcd_server_has_leader",
        "etcd_leader_changes":"rate(etcd_server_leader_changes_seen_total[1h])",
        "apiserver_5xx_rate": 'sum(rate(apiserver_request_total{code=~"5.."}[5m])) or vector(0)',
        "apiserver_p99":      'histogram_quantile(0.99, sum by(le,verb) (rate(apiserver_request_duration_seconds_bucket[5m])))',
        "cert_expiry_7d":     'sum(apiserver_client_certificate_expiration_seconds_bucket{le="604800"}) or vector(0)',
    }
    raw = _par(queries, cluster)
    return _par_result(raw)
