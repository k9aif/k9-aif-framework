# SPDX-License-Identifier: Apache-2.0
# K9-AIF Enterprise Insurance Operations Center
# RHEL UBI9 Python 3.11 — single image, 3 containers
#
# Build (from repo root):
#   sudo podman build -t k9-aif-eoc:latest .
#
# Pod launch:
#   bash run_eoc_pod.sh

FROM registry.access.redhat.com/ubi9/python-311:latest

USER root

# System packages needed for psycopg2 (PostgreSQL client)
RUN dnf install -y --nodocs \
      gcc \
      libpq-devel \
    && dnf clean all

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Copy full repo (k9_aif_abb + examples)
COPY k9_aif_abb ./k9_aif_abb
COPY examples   ./examples

# Make start scripts executable
RUN chmod +x examples/K9X_Enterprise_Insurance_OperationsCenter/start_eoc_app.sh \
             examples/K9X_Enterprise_Insurance_OperationsCenter/start_eoc_orchestrator.sh \
             examples/K9X_Enterprise_Insurance_OperationsCenter/start_eoc_router.sh

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    K9_ENV=production

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=8s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
      || exit 1

USER 1001

CMD ["bash", "examples/K9X_Enterprise_Insurance_OperationsCenter/start_eoc_app.sh"]