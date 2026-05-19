FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY triage ./triage
COPY frontend ./frontend
COPY README.md LICENSE ./

EXPOSE 8000

CMD ["python", "-m", "triage", "--serve", "--host", "0.0.0.0", "--port", "8000"]
