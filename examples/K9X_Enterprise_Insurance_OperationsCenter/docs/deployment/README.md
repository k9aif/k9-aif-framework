# EOC Deployment Guide — RHEL / Podman

This deploys the K9X Enterprise Insurance Operations Center as a **Podman pod** on RHEL with three containers sharing a single image:

| Container | Role | Port |
|---|---|---|
| `eoc-app-backend` | FastAPI + Web UI | 8000 (host: 8010) |
| `eoc-orchestrator` | Kafka consumer → squads → agents | — |
| `eoc-router` | Routes `eoc-events` → domain topics | — |

**Prerequisites running on your host (or network):**

- Ollama — model inference
- PostgreSQL — agent persistence + routing state
- Kafka / Redpanda — event bus
- Neo4j — graph sync agent
- RHEL with Podman (rootful)

---

## Step 1 — Clone the repo

```bash
git clone https://github.com/k9aif/k9-aif-framework.git
cd k9-aif-framework
```

Only two folders are needed at runtime — the framework and the example:

```
k9-aif-framework/
  k9_aif_abb/          ← framework (copied into image)
  examples/
    K9X_Enterprise_Insurance_OperationsCenter/   ← this example
  requirements.txt
  Dockerfile           ← built by run_eoc_pod.sh from the repo root
```

---

## Step 2 — Configure the environment (`.env`)

`config/config.yaml` reads every host and secret from environment variables
(`${OLLAMA_BASE_URL:-http://localhost:11434}`, `${POSTGRES_HOST:-localhost}`, `${KAFKA_BROKER:-localhost:9092}`,
`${NEO4J_URI:-bolt://localhost:7687}`, ...). Do not edit hosts or passwords into `config.yaml`.

```bash
cd examples/K9X_Enterprise_Insurance_OperationsCenter
cp env-example .env        # gitignored; never commit it
```

Set `OLLAMA_BASE_URL`, `POSTGRES_HOST` and `K9_PG_PASSWORD`, `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD`,
`KAFKA_BROKER`, and `REDIS_HOST`/`REDIS_PORT`/`REDIS_PASSWORD` for your environment.

At runtime, `config.yaml` is **volume-mounted** into the containers — so you can update it and restart
without rebuilding the image (see Step 6).

---

## Step 3 — Create the `.env` file

The pod script requires a minimal `.env` file for runtime flags. Create it at:

```
examples/K9X_Enterprise_Insurance_OperationsCenter/.env
```

```env
K9_ENV=production
K9_KAFKA_MODE=1
```

> `.env` is in `.gitignore` — it is never committed.

---

## Step 4 — Review and adjust the scripts

All deployment scripts are in this folder. Edit these values before running:

**`run_eoc_pod.sh`**

```bash
HOST_IP=<pod-host-ip>          # required: export it or prefix the command (HOST_IP=... bash run_eoc_pod.sh)
HOST_PORT=8010                 # host port mapped to container port 8000
VOLUME_BASE="/home/container_storage/volumes/eoc-dev"  # volume root on host
```

**`update_config_volume_mapped.sh`**

Update the source path to match your home directory:
```bash
cp ~/k9-aif-framework/examples/K9X_Enterprise_Insurance_OperationsCenter/config/*.yaml \
   /home/container_storage/volumes/eoc-dev/config
```

---

## Step 5 — Build and launch

Run from the **repo root** (the build context must include both `k9_aif_abb/` and `examples/`):

```bash
cd ~/k9-aif-framework
bash run_eoc_pod.sh
```

This will:
1. Build the container image (`k9-aif-eoc:latest`) from `Containerfile`
2. Remove the existing pod if it exists
3. Create the `eoc-dev` pod
4. Create volume directories and copy initial config
5. Start all three containers inside the pod

---

## Step 6 — Verify

```bash
sudo podman pod ps
sudo podman ps --pod

# Check logs per container
sudo podman logs eoc-app-backend
sudo podman logs eoc-orchestrator
sudo podman logs eoc-router
```

Endpoints (using `HOST_IP` and `HOST_PORT` from the script):

```
Web UI  : http://<HOST_IP>:8010/webui/
API     : http://<HOST_IP>:8010/docs
Health  : http://<HOST_IP>:8010/health
```

---

## Step 7 — Updating after a `git pull`

A container restart alone does **not** pick up code changes — the image must be rebuilt:

```bash
cd ~/k9-aif-framework
git pull
bash run_eoc_pod.sh          # rebuilds image + recreates pod
```

If you changed `config.yaml` only (no code change), use the faster update:

```bash
bash examples/K9X_Enterprise_Insurance_OperationsCenter/docs/deployment/update_config_volume_mapped.sh
sudo podman restart eoc-app-backend eoc-orchestrator eoc-router
```

---

## Volume layout

The pod mounts three host directories into all containers:

```
/home/container_storage/volumes/eoc-dev/
  config/     ← config.yaml (editable without rebuild)
  data/       ← runtime data files
  logs/       ← application logs
  runtime/    ← SQLite DBs, temp state
```

SELinux label is applied automatically by the script (`chcon -Rt container_file_t`).

---

## What is shown here

This deployment targets a **single RHEL host** running a rootful Podman pod — suited for a home lab or dev server. For production Kubernetes or OpenShift deployments, adapt `eoc-pod.yaml` (also in this folder) accordingly.
