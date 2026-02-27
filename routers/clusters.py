from fastapi import APIRouter
from typing import Any, Dict, List
from config import get_clusters

router = APIRouter(prefix="/api/observe", tags=["observe"])


@router.get("/clusters")
def list_clusters() -> List[Dict[str, Any]]:
    """Tanımlı tüm clusterları döner."""
    clusters = get_clusters()
    return [
        {
            "name":                 c["name"],
            "ocp_api":              c["ocp_api"],
            "insecure":             c["insecure"],
            "prometheus_url":       c.get("prometheus_url", ""),
            "loki_url":             c.get("loki_url", ""),
            "loki_available":       bool(c.get("loki_url")),
            "prometheus_available": bool(c.get("prometheus_url")),
        }
        for c in clusters.values()
    ]
