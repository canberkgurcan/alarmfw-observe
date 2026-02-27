from fastapi import APIRouter, Query, HTTPException
from typing import Any, Dict, List, Optional
import requests
from config import get_clusters, get_token

router = APIRouter(prefix="/api/observe", tags=["observe"])


def _ocp_get(ocp_api: str, insecure: bool, token: str, path: str, params: dict = None) -> dict:
    resp = requests.get(
        f"{ocp_api}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        params=params or {},
        timeout=15,
        verify=not insecure,
    )
    resp.raise_for_status()
    return resp.json()


def _resolve_cluster(cluster: str) -> Dict[str, Any]:
    clusters = get_clusters()
    if cluster not in clusters:
        raise HTTPException(404, f"Cluster '{cluster}' bulunamadı")
    c = clusters[cluster]
    if not c.get("ocp_api"):
        raise HTTPException(503, f"Cluster '{cluster}' için OCP API URL tanımlanmamış")
    return c


# ── Namespaces ────────────────────────────────────────────────────────────────

@router.get("/namespaces")
def list_namespaces(cluster: str = Query(...)) -> List[str]:
    """OpenShift projects (veya K8s namespaces) listesi."""
    c = _resolve_cluster(cluster)
    token = get_token(cluster)
    try:
        # Önce OpenShift projects API'sini dene
        try:
            data = _ocp_get(c["ocp_api"], c["insecure"], token,
                            "/apis/project.openshift.io/v1/projects")
        except Exception:
            data = _ocp_get(c["ocp_api"], c["insecure"], token, "/api/v1/namespaces")
        return sorted(item["metadata"]["name"] for item in data.get("items", []))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e))


# ── Pods ──────────────────────────────────────────────────────────────────────

@router.get("/pods")
def list_pods(
    cluster:   str = Query(...),
    namespace: str = Query(...),
) -> List[Dict[str, Any]]:
    """Namespace'teki pod listesi."""
    c = _resolve_cluster(cluster)
    token = get_token(cluster)
    try:
        data = _ocp_get(c["ocp_api"], c["insecure"], token,
                        f"/api/v1/namespaces/{namespace}/pods")
        pods = []
        for item in data.get("items", []):
            meta   = item.get("metadata", {})
            spec   = item.get("spec", {})
            status = item.get("status", {})

            conditions = {cond["type"]: cond["status"]
                          for cond in status.get("conditions", []) if "type" in cond}

            container_statuses = {cs["name"]: cs
                                  for cs in status.get("containerStatuses", [])}

            containers = []
            for co in spec.get("containers", []):
                cname = co.get("name", "")
                cs = container_statuses.get(cname, {})
                containers.append({
                    "name":     cname,
                    "image":    co.get("image", ""),
                    "ready":    cs.get("ready", False),
                    "restarts": cs.get("restartCount", 0),
                })

            pods.append({
                "name":       meta.get("name"),
                "namespace":  meta.get("namespace"),
                "phase":      status.get("phase"),
                "ready":      conditions.get("Ready", "False"),
                "containers": containers,
                "node":       spec.get("nodeName"),
                "created_at": meta.get("creationTimestamp"),
                "labels":     meta.get("labels", {}),
            })
        return pods
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e))


# ── Events ────────────────────────────────────────────────────────────────────

@router.get("/events")
def list_events(
    cluster:   str           = Query(...),
    namespace: str           = Query(...),
    pod:       Optional[str] = Query(None),
    kind:      Optional[str] = Query(None),
    event_type: Optional[str] = Query(None, alias="type"),
) -> List[Dict[str, Any]]:
    """Namespace'teki Kubernetes event listesi. pod ile filtrelenebilir."""
    c = _resolve_cluster(cluster)
    token = get_token(cluster)

    field_parts = []
    if pod:
        field_parts.append(f"involvedObject.name={pod}")
        field_parts.append(f"involvedObject.kind={kind or 'Pod'}")
    if event_type:
        field_parts.append(f"type={event_type}")

    params = {"fieldSelector": ",".join(field_parts)} if field_parts else {}

    try:
        data = _ocp_get(c["ocp_api"], c["insecure"], token,
                        f"/api/v1/namespaces/{namespace}/events", params)
        events = []
        for item in data.get("items", []):
            events.append({
                "type":       item.get("type"),
                "reason":     item.get("reason"),
                "message":    item.get("message"),
                "count":      item.get("count"),
                "first_time": item.get("firstTimestamp"),
                "last_time":  item.get("lastTimestamp"),
                "object":     item.get("involvedObject", {}).get("name"),
                "kind":       item.get("involvedObject", {}).get("kind"),
            })
        events.sort(key=lambda e: (e.get("last_time") or ""), reverse=True)
        return events
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e))
