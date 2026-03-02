from fastapi import APIRouter
from typing import Any, Dict, List
from config import (
    get_clusters, get_auth_status,
    get_cluster_prometheus_url, get_cluster_prometheus_token,
)

router = APIRouter(prefix="/api/observe", tags=["observe"])


@router.get("/auth")
def auth_status() -> Dict[str, Any]:
    """OCP cluster durumu. UI bu endpoint'i poll eder."""
    return get_auth_status()


@router.get("/clusters")
def list_clusters() -> List[Dict[str, Any]]:
    """Tanımlı tüm clusterları döner. Prometheus durumu cluster bazındadır."""
    clusters = get_clusters()
    result = []
    for c in clusters.values():
        cluster_name = c["name"]
        prom_url   = get_cluster_prometheus_url(cluster_name)
        prom_token = get_cluster_prometheus_token(cluster_name)
        result.append({
            "name":                 cluster_name,
            "ocp_api":              c["ocp_api"],
            "insecure":             c["insecure"],
            "prometheus_url":       prom_url,
            "loki_url":             c.get("loki_url", ""),
            "loki_available":       bool(c.get("loki_url")),
            "prometheus_available": bool(prom_url and prom_token),
        })
    return result
