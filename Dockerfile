FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV ARIA_OPEN_KNOWLEDGE_DB=data/aria_open_knowledge.sqlite3
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

# Acquire a small, source-backed starter corpus before serving requests.
# This is Wikimedia content acquisition, not an LLM call. User questions are
# still answered from the local corpus by KnowledgeManager.
CMD ["sh", "-c", "python -m brain.knowledge.open_knowledge seed --db \"${ARIA_OPEN_KNOWLEDGE_DB:-data/aria_open_knowledge.sqlite3}\" --limit \"${ARIA_KNOWLEDGE_SEED_LIMIT:-25}\" --delay 0.2; exec uvicorn main:app --host 0.0.0.0 --port \"${PORT:-10000}\""]
