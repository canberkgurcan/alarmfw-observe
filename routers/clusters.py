from fastapi import APIRouter
from typing import Any, Dict, List
from config import get_clusters, get_auth_status, get_global_prometheus_url, get_global_prometheus_token

router = APIRouter(prefix="/api/observe", tags=["observe"])


@router.get("/auth")
def auth_status() -> Dict[str, Any]:
    """Global Prometheus token durumu. UI bu endpoint'i poll eder."""
    return get_auth_status()


@router.get("/clusters")
def list_clusters() -> List[Dict[str, Any]]:
    """Tanımlı tüm clusterları döner. Prometheus durumu global token'a göre belirlenir."""
    clusters = get_clusters()
    prom_url = get_global_prometheus_url()
    prom_available = bool(prom_url and get_global_prometheus_token())
    return [
        {
            "name":                 c["name"],
            "ocp_api":              c["ocp_api"],
            "insecure":             c["insecure"],
            "prometheus_url":       prom_url,
            "loki_url":             c.get("loki_url", ""),
            "loki_available":       bool(c.get("loki_url")),
            "prometheus_available": prom_available,
        }
        for c in clusters.values()
    ]
