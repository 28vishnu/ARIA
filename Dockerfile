FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV ARIA_OPEN_KNOWLEDGE_DB=data/aria_open_knowledge.sqlite3
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

# Temporary diagnostics: seed the local corpus, then print database statistics
# and verify that a photosynthesis record can be searched before starting ARIA.
# No paid LLM API is used. Network requests here are only for Wikimedia ingestion.
CMD ["sh", "-c", "DB=\"${ARIA_OPEN_KNOWLEDGE_DB:-data/aria_open_knowledge.sqlite3}\"; echo '=== ARIA KNOWLEDGE SEED START ==='; python -u -m brain.knowledge.open_knowledge seed --db \"$DB\" --limit \"${ARIA_KNOWLEDGE_SEED_LIMIT:-25}\" --delay 0.2; echo '=== ARIA KNOWLEDGE DATABASE STATS ==='; python -u -m brain.knowledge.open_knowledge stats --db \"$DB\"; echo '=== ARIA PHOTOSYNTHESIS SEARCH TEST ==='; python -u -m brain.knowledge.open_knowledge search --db \"$DB\" --query photosynthesis --limit 5; echo '=== ARIA KNOWLEDGE DIAGNOSTICS COMPLETE ==='; exec uvicorn main:app --host 0.0.0.0 --port \"${PORT:-10000}\""]
