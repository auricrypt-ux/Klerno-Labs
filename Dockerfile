# ---- Build stage ----
FROM python:3.11-slim AS base

# Prevent Python from writing .pyc files & using buffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (add build tools only if you need to compile libs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Copy dependency list first for better caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy app code
COPY app /app/app

# Expose port (Render uses $PORT; we’ll forward to 8000 internally)
ENV PORT=8000
EXPOSE 8000

# Default command: run uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
