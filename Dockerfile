FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV ARIA_OPEN_KNOWLEDGE_DB=data/aria_open_knowledge.sqlite3
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

# Start the web server immediately so Render can detect the assigned port.
# Knowledge seeding is intentionally not run during web-service startup;
# run it as a separate one-off task after the service is healthy.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port \"${PORT:-10000}\""]
