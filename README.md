# alarmfw-observe

AlarmFW gözlem API'si. FastAPI tabanlı, port 8001. Prometheus ve OpenShift API'sine doğrudan bağlanır.

## Endpoints

| Endpoint | Açıklama |
|---|---|
| `GET /api/observe/clusters` | Tanımlı cluster listesi |
| `GET /api/observe/namespaces?cluster=` | Namespace listesi |
| `GET /api/observe/pods?cluster=&namespace=` | Pod listesi |
| `GET /api/observe/events?cluster=&namespace=` | Kubernetes event'leri |
| `GET /api/observe/alerts` | Prometheus firing alert'leri |
| `GET /api/observe/namespace-summary?cluster=&namespace=` | Pod sayıları özeti |
| `POST /api/observe/promql` | PromQL sorgusu çalıştır |
| `GET /api/observe/pod-metrics?pod=&namespace=` | Pod CPU/memory metrikleri |

Swagger UI: `http://localhost:8001/docs`

## Ortam Değişkenleri

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `ALARMFW_CONFIG` | `/config` | Config dizini (`observe.yaml` burada) |
| `ALARMFW_SECRETS` | `/secrets` | Token dosyaları (`<cluster>-prometheus.token` vb.) |

## Config Dosyası

`config/observe.yaml` (gitignore'da — gerçek URL'ler içerir):

```yaml
clusters:
  - name: cluster-adi
    ocp_api: https://api.cluster.domain:6443
    insecure: true
    prometheus_url: https://thanos-querier.apps.cluster.domain
    prometheus_token_file: /secrets/cluster-adi-prometheus.token
```

Şablonu kopyala:
```bash
cp config/observe.yaml.example config/observe.yaml
```

## Geliştirme

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

## Docker

```bash
docker build -t alarmfw-observe:latest .
docker run -p 8001:8001 \
  -e ALARMFW_CONFIG=/config \
  -e ALARMFW_SECRETS=/secrets \
  -v /path/to/config:/config:ro \
  -v /path/to/secrets:/secrets:ro \
  alarmfw-observe:latest
```

## OCP Deploy

```bash
oc apply -f ocp/deployment.yaml -n alarmfw-prod
oc set image deployment/alarmfw-observe alarmfw-observe=REGISTRY/alarmfw-observe:TAG -n alarmfw-prod
```

## Jenkins Pipeline

4 stage: **Checkout SCM → Docker Build → Nexus Push → OCP Deploy**

| Değişken | Açıklama |
|---|---|
| `REGISTRY_URL` | Nexus registry adresi |
| `REGISTRY_CREDS` | Jenkins credential ID (Docker kullanıcı/şifre) |
| `OCP_API_URL` | OpenShift API endpoint |
| `OCP_TOKEN_CREDS` | Jenkins credential ID (OCP service account token) |
| `DEPLOY_NAMESPACE` | Deploy namespace (ör: `alarmfw-prod`) |
