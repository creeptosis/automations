FROM python:3.12-slim

# tzdata so TZ=Asia/Kuala_Lumpur works (dates drive "today" and check-ins)
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 HOST=0.0.0.0
EXPOSE 5001
CMD ["python", "scripts/gui.py"]
