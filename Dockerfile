FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    portaudio19-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd -m appuser && mkdir -p /app/data /app/logs /app/uploads_tmp && chown -R appuser:appuser /app

COPY --chown=appuser:appuser . .

USER appuser

ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5001/api/health || exit 1

CMD ["python", "run.py"]
