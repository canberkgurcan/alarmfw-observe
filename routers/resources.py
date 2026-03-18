from fastapi import APIRouter, Query, HTTPException
from typing import Any, Dict, List, Optional
import requests
import time
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

    # Pod durumunu al — container adı ve CrashLoopBackOff tespiti için
    resolved_container = container
    is_crash_loop = False
    try:
        pod_data = _ocp_get(c["ocp_api"], c["insecure"], token,
                            f"/api/v1/namespaces/{namespace}/pods/{pod}")
        container_statuses = pod_data.get("status", {}).get("containerStatuses", [])
        spec_containers = [co["name"] for co in pod_data.get("spec", {}).get("containers", [])]

        if not resolved_container:
            if len(spec_containers) > 1:
                not_ready = [cs["name"] for cs in container_statuses if not cs.get("ready", True)]
                resolved_container = not_ready[0] if not_ready else spec_containers[0]
            elif len(spec_containers) == 1:
                resolved_container = spec_containers[0]

        # CrashLoopBackOff tespiti: waiting.reason == "CrashLoopBackOff"
        for cs in container_statuses:
            waiting = cs.get("state", {}).get("waiting", {})
            if waiting.get("reason") == "CrashLoopBackOff":
                is_crash_loop = True
                break
    except Exception:
        pass

    log_url = f"{c['ocp_api']}/api/v1/namespaces/{namespace}/pods/{pod}/log"
    log_headers = {"Authorization": f"Bearer {token}", "Accept": "text/plain"}
    base_params: Dict[str, Any] = {"tailLines": tail_lines}
    if resolved_container:
        base_params["container"] = resolved_container

    def _fetch(params: Dict[str, Any]) -> requests.Response:
        return requests.get(log_url, headers=log_headers, params=params,
                            timeout=30, verify=not c["insecure"])

    def _success(resp: requests.Response, is_prev: bool, fallback_used: bool = False, fallback_from: int = None):
        resp.raise_for_status()
        return {
            "ok": True, "pod": pod, "container": resolved_container,
            "logs": resp.text, "previous": is_prev,
            "fallback_used": fallback_used, "fallback_from_status": fallback_from,
        }

    def _unavailable(reason: str, prev_status: int = None):
        detail = f" (previous HTTP {prev_status})" if prev_status else ""
        return {
            "ok": False, "pod": pod, "container": resolved_container,
            "logs": None, "previous": False, "unavailable": True,
            "unavailable_reason": f"{reason}{detail}",
        }

    try:
        if previous:
            # Kullanıcı doğrudan previous istedi
            resp = _fetch({**base_params, "previous": "true"})
            if resp.status_code == 200:
                return _success(resp, is_prev=True)
            resp2 = _fetch(base_params)
            if resp2.status_code == 200:
                return _success(resp2, is_prev=False, fallback_used=True)
            return _unavailable("Log mevcut değil.")

        if is_crash_loop:
            # CrashLoopBackOff: önce previous log dene (son crash'in logları en güvenilir)
            prev_resp = _fetch({**base_params, "previous": "true"})
            if prev_resp.status_code == 200:
                return _success(prev_resp, is_prev=True)

            # Previous başarısız — container tam o an yeniden başlamış olabilir.
            # Kısa aralıklarla current'ı dene (container kısa süre Running olacak).
            for delay in (0, 2, 3):
                if delay:
                    time.sleep(delay)
                cur_resp = _fetch(base_params)
                if cur_resp.status_code == 200:
                    return _success(cur_resp, is_prev=False, fallback_used=True,
                                    fallback_from=prev_resp.status_code)

            return _unavailable(
                "CrashLoopBackOff: container backoff bekleme sürecinde, log yakalanamadı.",
                prev_status=prev_resp.status_code,
            )

        # Normal akış (Running, Pending, vb.)
        resp = _fetch(base_params)
        if resp.status_code == 200:
            return _success(resp, is_prev=False)
        if resp.status_code == 406:
            # Pending/ImagePullBackOff — previous dene
            prev_resp = _fetch({**base_params, "previous": "true"})
            if prev_resp.status_code == 200:
                return _success(prev_resp, is_prev=True, fallback_used=True, fallback_from=406)
            return _unavailable("Container henüz başlamadı veya log mevcut değil (406).",
                                prev_status=prev_resp.status_code)
        resp.raise_for_status()
        return _unavailable("Beklenmedik durum.")

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
