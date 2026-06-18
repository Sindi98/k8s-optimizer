FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Backend deps
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
# Per usare Claude o OpenAI come provider, scommentare:
# RUN pip install --no-cache-dir anthropic openai

# App code + frontend
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Esegue come utente non-root
RUN useradd -u 10001 -m appuser
USER 10001

WORKDIR /app/backend
EXPOSE 8080

# DEMO_MODE va sovrascritto a "false" in produzione (vedi k8s/deploy.yaml).
ENV DEMO_MODE=false IN_CLUSTER=true
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
