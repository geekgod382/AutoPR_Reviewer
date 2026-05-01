# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Install ruff system-wide so static analysis can invoke it
RUN pip install --no-cache-dir ruff

# Install Node.js and ESLint for JS/TS static analysis
RUN apt-get update && apt-get install -y nodejs npm
RUN npm install -g eslint

COPY --from=builder /install /usr/local

COPY app/ ./app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
