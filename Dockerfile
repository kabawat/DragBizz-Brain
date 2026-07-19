FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system dragbizz \
    && adduser --system --ingroup dragbizz dragbizz

COPY pyproject.toml ./
COPY app ./app

RUN pip install .

USER dragbizz

EXPOSE 3000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
