import os
import logging
from pathlib import Path
from typing import Any, Dict, List
import yaml

ALARMFW_CONFIG  = Path(os.getenv("ALARMFW_CONFIG",  "/home/cnbrkgrcn/projects/alarmfw/config"))
ALARMFW_SECRETS = Path(os.getenv("ALARMFW_SECRETS", "/home/cnbrkgrcn/alarmfw-secrets"))

OCP_CONF_DIR = ALARMFW_CONFIG / "generated"
OBSERVE_CONF = ALARMFW_CONFIG / "observe.yaml"
DEFAULT_PROM_TIMEOUT_SEC = 20

log = logging.getLogger("alarmfw.observe.config")


def _is_true(v: str | None) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "on"}


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        log.warning("YAML parse failed for '%s': %s", path, e)
        return {}


def _read_secret(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception as e:
        log.warning("Secret read failed for '%s': %s", path, e)
        return ""


def _load_observe_yaml() -> Dict[str, Any]:
    if not OBSERVE_CONF.exists():
        return {}
    return _load_yaml(OBSERVE_CONF)


def get_clusters() -> Dict[str, Dict[str, Any]]:
    """
    generated/ yaml'larından ocp_pod_health clusterlarını toplar.
    observe.yaml varsa Loki URL ve overrideları birleştirir.
    Döner: {cluster_name: {name, ocp_api, insecure, token_file, loki_url}}
    """
    clusters: Dict[str, Dict[str, Any]] = {}

    if OCP_CONF_DIR.exists():
        for f in OCP_CONF_DIR.glob("*.yaml"):
            data = _load_yaml(f)
            for check in data.get("checks", []) or []:
                if not check.get("enabled", True):
                    continue
                if check.get("type") not in ("ocp_pod_health", "ocp_cluster_snapshot"):
                    continue
                params = check.get("params", {}) or {}
                name = params.get("cluster", "")
                if not name or name in clusters:
                    continue
                clusters[name] = {
                    "name":       name,
                    "ocp_api":    params.get("ocp_api", "").rstrip("/"),
                    "insecure":   str(params.get("ocp_insecure", "false")).lower() == "true",
                    "token_file": str(ALARMFW_SECRETS / f"{name}.token"),
                    "loki_url":   "",
                }

    obs = _load_observe_yaml()
    for cname, cdata in (obs.get("clusters") or {}).items():
        if cname in clusters:
            clusters[cname].update(cdata)
        else:
            token_file = str(ALARMFW_SECRETS / f"{cname}.token")
            clusters[cname] = {"name": cname, "ocp_api": "", "insecure": True,
                                "token_file": token_file, "loki_url": "", **cdata}

    return clusters


def get_token(cluster_name: str) -> str:
    """OCP API token'ı (/secrets/<cluster>.token)"""
    return _read_secret(ALARMFW_SECRETS / f"{cluster_name}.token")


# ── Global Prometheus ──────────────────────────────────────────────────────────

def get_global_prometheus_url() -> str:
    """Global Prometheus URL — env PROMETHEUS_URL veya observe.yaml global.prometheus_url"""
    env_url = os.getenv("PROMETHEUS_URL", "").strip()
    if env_url:
        return env_url
    obs = _load_observe_yaml()
    return ((obs.get("global") or {}).get("prometheus_url") or "").strip()


def get_global_prometheus_token() -> str:
    """Global Prometheus token — /secrets/prometheus.token"""
    return _read_secret(ALARMFW_SECRETS / "prometheus.token")


def get_global_prometheus_insecure() -> bool:
    """
    TLS doğrulamasını kapatma flag'i.
    Öncelik: PROMETHEUS_INSECURE env > observe.yaml global.prometheus_insecure
    """
    env_val = os.getenv("PROMETHEUS_INSECURE")
    if env_val is not None:
        return _is_true(env_val)

    obs = _load_observe_yaml()
    global_cfg = (obs.get("global") or {})
    return _is_true(str(global_cfg.get("prometheus_insecure", "")))


def get_global_prometheus_verify_tls() -> bool:
    return not get_global_prometheus_insecure()


def get_global_prometheus_timeout_sec() -> int:
    """
    Prometheus HTTP timeout (sec).
    Öncelik: PROMETHEUS_TIMEOUT_SEC env > observe.yaml global.prometheus_timeout_sec
    """
    env_val = os.getenv("PROMETHEUS_TIMEOUT_SEC")
    if env_val:
        try:
            return max(1, int(env_val))
        except ValueError:
            log.warning("Invalid PROMETHEUS_TIMEOUT_SEC='%s', using default=%s", env_val, DEFAULT_PROM_TIMEOUT_SEC)

    obs = _load_observe_yaml()
    global_cfg = (obs.get("global") or {})
    raw_timeout = global_cfg.get("prometheus_timeout_sec", DEFAULT_PROM_TIMEOUT_SEC)
    try:
        return max(1, int(raw_timeout))
    except (TypeError, ValueError):
        log.warning(
            "Invalid observe.yaml global.prometheus_timeout_sec='%s', using default=%s",
            raw_timeout,
            DEFAULT_PROM_TIMEOUT_SEC,
        )
        return DEFAULT_PROM_TIMEOUT_SEC


def get_auth_status() -> Dict[str, Any]:
    """Prometheus token dosyası var ve dolu mu?"""
    token = get_global_prometheus_token()
    prom_url = get_global_prometheus_url()
    return {
        "logged_in":   bool(token),
        "has_token":   bool(token),
        "has_prom_url": bool(prom_url),
    }


# ── Loki (ileride) ─────────────────────────────────────────────────────────────

def get_loki_token(cluster_name: str) -> str:
    """Loki token'ı (/secrets/<cluster>-loki.token)"""
    return _read_secret(ALARMFW_SECRETS / f"{cluster_name}-loki.token")
