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


# ── Pod Logs ──────────────────────────────────────────────────────────────────

@router.get("/pod-logs")
def get_pod_logs(
    cluster:    str           = Query(...),
    namespace:  str           = Query(...),
    pod:        str           = Query(...),
    container:  Optional[str] = Query(None),
    tail_lines: int           = Query(200, ge=1, le=2000),
    previous:   bool          = Query(False),
) -> Dict[str, Any]:
    """Pod log içeriği (son tail_lines satır, max 2000)."""
    c = _resolve_cluster(cluster)
    token = get_token(cluster)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # container belirtilmemişse pod spec'ten otomatik seç
    resolved_container = container
    if not resolved_container:
        try:
            pod_data = _ocp_get(c["ocp_api"], c["insecure"], token,
                                f"/api/v1/namespaces/{namespace}/pods/{pod}")
            container_statuses = pod_data.get("status", {}).get("containerStatuses", [])
            spec_containers = [co["name"] for co in pod_data.get("spec", {}).get("containers", [])]

            if len(spec_containers) > 1:
                # ready=False olan ilk container'ı seç (kırık olan); yoksa ilki
                not_ready = [cs["name"] for cs in container_statuses if not cs.get("ready", True)]
                resolved_container = not_ready[0] if not_ready else spec_containers[0]
            elif len(spec_containers) == 1:
                resolved_container = spec_containers[0]
        except Exception:
            pass  # container None kalırsa tek-container pod'larda OCP zaten döner

    log_url = f"{c['ocp_api']}/api/v1/namespaces/{namespace}/pods/{pod}/log"
    log_headers = {"Authorization": f"Bearer {token}", "Accept": "text/plain"}
    base_params: Dict[str, Any] = {"tailLines": tail_lines}
    if resolved_container:
        base_params["container"] = resolved_container

    def _fetch(params: Dict[str, Any]) -> requests.Response:
        return requests.get(log_url, headers=log_headers, params=params,
                            timeout=30, verify=not c["insecure"])

    def _handle_resp(resp: requests.Response, is_previous: bool, fallback_used: bool = False, fallback_from_status: int = None):
        if resp.status_code == 406:
            # Container henüz başlamadı (Pending/ImagePullBackOff vb.) — log mevcut değil
            return {
                "ok": False, "pod": pod, "container": resolved_container,
                "logs": None, "previous": is_previous,
                "fallback_used": fallback_used, "fallback_from_status": fallback_from_status,
                "unavailable": True,
                "unavailable_reason": "Container henüz başlamadı veya log mevcut değil (406).",
            }
        resp.raise_for_status()
        return {
            "ok": True, "pod": pod, "container": resolved_container,
            "logs": resp.text, "previous": is_previous,
            "fallback_used": fallback_used, "fallback_from_status": fallback_from_status,
        }

    try:
        if previous:
            resp = _fetch({**base_params, "previous": "true"})
            if resp.status_code in (400, 404):
                # previous log yok, mevcut log'a fallback
                fallback_status = resp.status_code
                resp = _fetch(base_params)
                return _handle_resp(resp, is_previous=False, fallback_used=True, fallback_from_status=fallback_status)
            return _handle_resp(resp, is_previous=True)
        else:
            resp = _fetch(base_params)
            return _handle_resp(resp, is_previous=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e))


# ── Namespace Summary ─────────────────────────────────────────────────────────

@router.get("/namespace-summary")
def namespace_summary(
    cluster:   str = Query(...),
    namespace: str = Query(...),
) -> Dict[str, Any]:
    """Namespace özeti: pod fazları, toplam restart sayısı, Warning event sayısı."""
    c = _resolve_cluster(cluster)
    token = get_token(cluster)
    running = failed = pending = total_restarts = 0
    warning_events = 0

    try:
        pod_data = _ocp_get(c["ocp_api"], c["insecure"], token,
                            f"/api/v1/namespaces/{namespace}/pods")
        for item in pod_data.get("items", []):
            phase = item.get("status", {}).get("phase", "")
            if phase == "Running":   running += 1
            elif phase == "Failed":  failed += 1
            elif phase == "Pending": pending += 1
            for cs in item.get("status", {}).get("containerStatuses", []):
                total_restarts += cs.get("restartCount", 0)
    except Exception:
        pass

    try:
        ev_data = _ocp_get(c["ocp_api"], c["insecure"], token,
                           f"/api/v1/namespaces/{namespace}/events",
                           {"fieldSelector": "type=Warning"})
        warning_events = len(ev_data.get("items", []))
    except Exception:
        pass

    return {
        "running":        running,
        "failed":         failed,
        "pending":        pending,
        "total_restarts": total_restarts,
        "warning_events": warning_events,
    }
