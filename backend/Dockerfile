FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt requirements-ai.txt ./
ARG AI_EXTRAS=false
RUN pip install --no-cache-dir -r requirements.txt && if [ "$AI_EXTRAS" = "true" ]; then pip install --no-cache-dir -r requirements-ai.txt; fi
COPY citymate ./citymate
COPY migrations ./migrations
COPY alembic.ini ./
RUN useradd --create-home app && mkdir -p /app/data/citymate && chown -R app:app /app/data
USER app
CMD ["uvicorn", "citymate.app:app", "--host", "0.0.0.0", "--port", "8000"]
