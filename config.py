import os
from pathlib import Path
from typing import Any, Dict, List
import yaml

ALARMFW_CONFIG  = Path(os.getenv("ALARMFW_CONFIG",  "/home/cnbrkgrcn/projects/alarmfw/config"))
ALARMFW_SECRETS = Path(os.getenv("ALARMFW_SECRETS", "/home/cnbrkgrcn/alarmfw-secrets"))

OCP_CONF_DIR = ALARMFW_CONFIG / "generated"
OBSERVE_CONF = ALARMFW_CONFIG / "observe.yaml"


def _load_observe_yaml() -> Dict[str, Any]:
    if not OBSERVE_CONF.exists():
        return {}
    try:
        return yaml.safe_load(OBSERVE_CONF.read_text()) or {}
    except Exception:
        return {}


def get_clusters() -> Dict[str, Dict[str, Any]]:
    """
    generated/ yaml'larından ocp_pod_health clusterlarını toplar.
    observe.yaml varsa Loki URL ve overrideları birleştirir.
    Döner: {cluster_name: {name, ocp_api, insecure, token_file, loki_url}}
    """
    clusters: Dict[str, Dict[str, Any]] = {}

    if OCP_CONF_DIR.exists():
        for f in OCP_CONF_DIR.glob("*.yaml"):
            try:
                data = yaml.safe_load(f.read_text()) or {}
            except Exception:
                continue
            for check in data.get("checks", []) or []:
                if not check.get("enabled", True):
                    continue
                if check.get("type") != "ocp_pod_health":
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
    try:
        return (ALARMFW_SECRETS / f"{cluster_name}.token").read_text().strip()
    except Exception:
        return ""


def get_prometheus_token(cluster_name: str) -> str:
    """Prometheus token'ı (/secrets/<cluster>-prometheus.token)"""
    try:
        return (ALARMFW_SECRETS / f"{cluster_name}-prometheus.token").read_text().strip()
    except Exception:
        return ""


def get_loki_token(cluster_name: str) -> str:
    """Loki token'ı (/secrets/<cluster>-loki.token)"""
    try:
        return (ALARMFW_SECRETS / f"{cluster_name}-loki.token").read_text().strip()
    except Exception:
        return ""
