# --- 1. Base Image ---
FROM python:3.10-slim

# --- 2. Environment Variables ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRANSFORMERS_OFFLINE=1

# --- 3. Set Workdir ---
WORKDIR /app

# --- 4. Copy Only requirements.txt (for Docker cache optimization) ---
COPY requirements.txt .

# --- 5. Install Dependencies ---
RUN apt-get update && apt-get install -y \
    gcc python3-dev build-essential \
    curl git \
    libglib2.0-0 libsm6 libxext6 libxrender-dev ffmpeg \
    default-jdk \
    # fonts-nanum \
 && pip install --no-cache-dir -r requirements.txt \
 && apt-get purge -y --auto-remove gcc python3-dev build-essential \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# --- 6. Environment Variable for Java (needed by JPype/konlpy) ---
ENV JAVA_HOME="/usr/lib/jvm/java-11-openjdk-amd64"
ENV PATH="$JAVA_HOME/bin:$PATH"

# --- 7. Copy Models ---
COPY ./models/bart /app/models/bart
COPY ./models/eenzeenee_t5 /app/models/eenzeenee_t5

# --- 8. Copy Fonts and Source Code ---
COPY ./fonts /app/fonts
COPY . .

# --- 9. Run App with Gunicorn (Production Server) ---
# EXPOSE 8080은 Cloud Run에서 사용하지 않으므로 삭제
# Gunicorn을 사용하여 api_server.py 내부의 'app' 객체를 실행
# Cloud Run이 주입하는 $PORT 환경 변수를 사용

# [변경] --threads 제거, --worker-connections 1000 추가
# CMD ["gunicorn", "--bind", "0.0.0.0:$PORT", "--workers", "1", "-k", "gevent", "--worker-connections", "1000", "--timeout", "300", "api_server:app"]

# [변경] -k gevent (비동기 워커) 사용
# [변경] --preload는 반드시 제거된 상태여야 함
# [변경] --timeout 120초 (시작이 빠르므로 300초 불필요)
# CMD ["gunicorn", "--bind", "0.0.0.0:$PORT", "--workers", "1", "-k", "gevent", "--worker-connections", "1000", "--timeout", "120", "api_server:app"]
# [변경] Gunicorn CMD 대신 Python을 직접 실행
CMD ["python", "api_server.py"]