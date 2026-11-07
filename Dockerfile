FROM python:3.14.10-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot/ bot/
COPY scripts/ scripts/
CMD ["python", "-m", "bot"]
