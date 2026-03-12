from main import health
from routers.clusters import auth_status
from routers.metrics import run_promql


def test_health_endpoint():
    assert health() == {"status": "ok"}


def test_auth_status_shape():
    data = auth_status()
    assert isinstance(data["logged_in"], bool)
    assert isinstance(data["has_token"], bool)
    assert isinstance(data["has_prom_url"], bool)


def test_promql_rejects_empty_query():
    data = run_promql({"query": ""})
    assert data["ok"] is False
    assert data["result"] == []
