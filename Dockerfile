# TenderScope - kontejner pro bezplatny hosting (Hugging Face Spaces, Render, ...)
FROM python:3.15-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860 \
    TS_HOST=0.0.0.0 \
    TS_VEREJNE=1 \
    TS_AUTO_AKTUALIZACE=rychle

# Hugging Face spousti kontejner pod uzivatelem s UID 1000
RUN useradd -m -u 1000 user
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=user . .
RUN mkdir -p data vystupy && chown -R user:user /app
USER user

EXPOSE 7860
CMD ["python", "server.py", "--neotvirat"]
