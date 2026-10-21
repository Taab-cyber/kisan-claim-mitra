# Kisan Claim Mitra - one container: web app + agent + mock portal.
# Works on Hugging Face Spaces (Docker SDK, port 7860) and Render free tier.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    VOICE_PROVIDER=browser

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Train our own NLU model at build time (synthetic data, ~5 seconds, no downloads).
RUN python -m agent.nlu.gen_data && python -m agent.nlu.train

# Hugging Face Spaces runs containers as user 1000.
RUN useradd -m -u 1000 user && chown -R user /app
USER user

EXPOSE 7860
# SQLite is re-seeded on every start (in-memory by default).
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
