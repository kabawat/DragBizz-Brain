FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system dragbizz \
    && adduser --system --ingroup dragbizz dragbizz

COPY pyproject.toml ./
COPY app ./app
COPY knowledge ./knowledge

RUN pip install .

COPY docker-entrypoint.py /docker-entrypoint.py

EXPOSE 4004

# Starts as root so it can fix ./data permissions, then drops to dragbizz.
ENTRYPOINT ["python", "/docker-entrypoint.py"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4004"]
