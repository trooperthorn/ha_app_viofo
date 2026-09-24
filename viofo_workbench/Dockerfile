FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libimage-exiftool-perl fonts-dejavu-core ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV PYTHONUNBUFFERED=1 VIOFO_DATA=/data VIOFO_HA=1
EXPOSE 8099 8100
CMD ["python", "-m", "app.server"]
