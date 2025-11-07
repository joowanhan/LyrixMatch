# --- 1. Base Image ---
# FROM python:3.10-slim
FROM python:3.10-slim-bullseye

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
    curl git gnupg \
    curl git git-lfs \
    libglib2.0-0 libsm6 libxext6 libxrender-dev ffmpeg \
    openjdk-11-jdk-headless \
    # fonts-nanum \
# --- git-lfs 저장소 설정 스크립트 실행 ---
 && curl -s https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh | bash \
# --- 새 저장소 목록 갱신 및 git-lfs 설치 ---
 && apt-get update \
 && apt-get install -y git-lfs \
 # ----------------------------------------
 && pip install --no-cache-dir -r requirements.txt \
 # NLTK 데이터를 이미지 빌드 시점에 /usr/share/nltk_data 경로에 다운로드
 && python -m nltk.downloader -d /usr/share/nltk_data stopwords punkt \
 && apt-get purge -y --auto-remove gcc python3-dev build-essential gnupg \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# --- 6. Environment Variable for Java (needed by JPype/konlpy) ---
ENV JAVA_HOME="/usr/lib/jvm/java-11-openjdk-amd64"
ENV PATH="$JAVA_HOME/bin:$PATH"

# --- 7. Copy Models ---
# [삭제] 8번 단계의 "COPY . ."가 모든 파일을 복사하므로 이 단계는 불필요.
# COPY ./models/bart /app/models/bart
# COPY ./models/eenzeenee_t5 /app/models/eenzeenee_t5

# --- 8. Copy Fonts and Source Code ---
COPY ./fonts /app/fonts
COPY . .

# --- [추가] LFS Pointer 파일을 실제 파일로 변환 ---
# .dockerignore에서 .git을 제외했으므로, "COPY . ."가 .git 디렉토리를 복사함
# 복사된 .git 정보를 바탕으로 LFS 파일을 다운로드함
RUN git lfs pull

# --- 9. Run App with Gunicorn (Production Server) ---
# [변경] Gunicorn CMD 대신 Python을 직접 실행
CMD ["python", "api_server.py"]