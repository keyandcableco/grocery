FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# 120 s, not gunicorn's 30: /api/capture can wait on Haiku, and /api/record?wait=
# holds the reply up to 75 s for Whisper (grocery_app/recordings.py). Threads keep
# a waiting call from blocking the pages.
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "2", "--threads", "4", "--timeout", "120", "app:app"]
