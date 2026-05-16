FROM python:3.11-slim

# ffmpeg + 한국어 폰트 (OG 이미지 생성용)
RUN apt-get update && apt-get install -y ffmpeg fonts-noto-cjk && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --upgrade yt-dlp

COPY . .

ENV PORT=5000

CMD ["python", "app.py"]
