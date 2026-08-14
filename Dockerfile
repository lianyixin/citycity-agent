FROM python:3.11-slim
WORKDIR /app

# Install backend dependencies (includes psycopg2-binary, sqlalchemy, dotenv)
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend application code + migration scripts
COPY backend/ /app/backend/

# Copy optional seed data
COPY data/ /app/data/

# Copy root-level scripts (import_seed.py)
COPY scripts/ /app/scripts/

# Copy pre-built frontend dist. Build it before `docker build`; secrets are
# injected at runtime and must never be copied into the image.
COPY frontend/dist /app/frontend/dist

ENV PYTHONPATH=/app/backend

# Default: run FastAPI server. Override via `--command` for migration Job.
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000"]
