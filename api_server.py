# api_server.py (Refactored)

from spotipy.oauth2 import SpotifyOAuth
import spotipy
from flask import request, redirect
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import json
import os

# 모니터링 엔드포인트 를 위한 모듈 추가
# 시스템의 자원(메모리 등)을 확인하기 위한 psutil
# 최근 요청 기록을 효율적으로 관리하기 위한 collections.deque
from collections import deque
import psutil
import datetime

# --- 모듈 임포트 ---
# 각 모듈의 역할에 맞는 함수만 가져온다.
from get_lyrics_save_firestore import process_playlist_and_save_to_firestore
from lyrics_analyzer_firestore import process_lyrics
from wc import generate_wordcloud_and_upload_to_gcs
import firebase_admin
from firebase_admin import credentials, firestore

# .env 로드 및 Firebase 앱 초기화
load_dotenv()
try:
    if not firebase_admin._apps:
        # GOOGLE_APPLICATION_CREDENTIALS 환경변수를 사용한 기본 초기화
        cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)
        print("✅ Firebase App initialized successfully.")
except Exception as e:
    print(f"❌ Firebase App initialization failed: {e}")
db = firestore.client()


app = Flask(__name__)
CORS(app)  # Flutter에서 요청할 수 있게 허용

# ───── 최근 요청 5개를 저장하기 위한 전역 변수 추가 ─────
recent_requests = deque(maxlen=5)


# ──────────────────────────────────────────────────
# ───── 로깅을 위한 데코레이터 추가 ─────
# 모든 요청이 실행되기 전에 로그를 기록한다.
@app.before_request
def log_request_info():
    # /debug 엔드포인트 자체에 대한 요청은 기록에서 제외하여 순환을 방지한다.
    if request.path != "/debug":
        recent_requests.append(
            {
                "timestamp": datetime.datetime.now().isoformat(),
                "method": request.method,
                "path": request.path,
                "remote_addr": request.remote_addr,
            }
        )


# ────────────────────────────────
# 헬퍼 함수: Firestore에서 특정 곡을 찾는 중복 코드를 하나의 함수로 통합
def _get_song_data_from_firestore(doc_id: str, song_title: str) -> dict:
    """Firestore에서 특정 곡의 데이터를 찾아 반환하는 헬퍼 함수"""
    doc_ref = db.collection("user_playlists").document(doc_id)
    doc = doc_ref.get()

    if not doc.exists:
        return None  # 문서 없음

    playlist_data = doc.to_dict()
    tracks = playlist_data.get("tracks", [])

    for song in tracks:
        # 클라이언트가 보낸 제목과 일치하는 곡을 찾는다.
        if song.get("clean_title") == song_title:
            return song  # 찾은 곡의 딕셔너리 전체를 반환

    return None  # 해당 곡을 찾지 못함


# ────────────────────────────────
# API 엔드포인트


# api_server.py에 추가 (05/23) -> firestore 업데이트에 맞춰 수정(10/15)
@app.route("/crawl", methods=["POST"])
def crawl_playlist():
    data = request.get_json()
    playlist_url = data.get("playlist_url")
    if not playlist_url:
        return jsonify({"error": "Missing playlist_url"}), 400

    try:
        # Firestore에 저장 후 고유 문서 ID를 반환받는다.
        doc_id = process_playlist_and_save_to_firestore(playlist_url)
        if doc_id:
            # 클라이언트에게 이 ID를 전달한다.
            return jsonify({"doc_id": doc_id}), 200
        else:
            return jsonify({"error": "플레이리스트 처리 중 서버 오류 발생"}), 500
    except Exception as e:
        print(f"Error during crawl: {e}")  # 디버깅을 위한 로그 추가
        return jsonify({"error": f"처리 중 오류: {str(e)}"}), 500


# ────────────────────────────────


@app.route("/analyze/<string:doc_id>/<string:song_title>", methods=["GET"])
def analyze_song(doc_id, song_title):
    """Firestore에서 특정 곡의 가사를 가져와 요약 및 키워드를 반환"""
    song_data = _get_song_data_from_firestore(doc_id, song_title)
    if not song_data:
        return jsonify({"error": "해당 곡을 찾을 수 없습니다."}), 404

    lyrics = song_data.get("lyrics_processed", "")
    if not lyrics:
        return jsonify({"error": "분석할 가사 데이터가 없습니다."}), 400

    summary, keywords = process_lyrics(lyrics)
    return jsonify({"summary": summary, "keywords": keywords})


# ────────────────────────────────


@app.route("/quizdata/<string:doc_id>", methods=["GET"])
def get_quizdata_from_firestore(doc_id):
    """
    Firestore 문서 ID를 기반으로 퀴즈 데이터를 생성하여 반환한다.
    """
    try:
        # Firestore에서 doc_id로 문서를 가져온다.
        doc_ref = db.collection("user_playlists").document(doc_id)
        doc = doc_ref.get()

        if not doc.exists:
            return (
                jsonify({"error": "해당 ID의 플레이리스트 데이터를 찾을 수 없습니다."}),
                404,
            )

        playlist_data = doc.to_dict()
        tracks = playlist_data.get("tracks", [])

        quiz_result = []
        for song in tracks:
            lyrics = song.get("lyrics_processed", "")
            if not lyrics.strip():
                continue

            # 가사 요약 및 키워드 추출
            summary, keywords = process_lyrics(lyrics)
            quiz_result.append(
                {
                    "title": song.get("clean_title"),
                    "artist": song.get("artist"),
                    "summary": summary,
                    "keywords": keywords,
                    "lyrics": lyrics,  # 워드클라우드 생성을 위해 원본 가사도 전달
                }
            )

        return jsonify(quiz_result)
    except Exception as e:
        print(f"Quizdata 생성 오류: {e}")
        return jsonify({"error": "퀴즈 데이터 생성 중 오류 발생"}), 500


# ────────────────────────────────
# wc endpoint 추가 (05/29) -> GCS 업데이트(10/15)


@app.route("/wordcloud/<string:doc_id>/<string:song_title>", methods=["GET"])
def get_wordcloud_for_song(doc_id, song_title):
    """Firestore에서 특정 곡의 정보를 가져와 워드클라우드를 생성하고 URL을 반환"""
    song_data = _get_song_data_from_firestore(doc_id, song_title)
    if not song_data:
        return jsonify({"error": "해당 곡을 찾을 수 없습니다."}), 404

    lyrics = song_data.get("lyrics_processed", "")
    artist = song_data.get("artist", "Unknown")

    if not lyrics:
        return jsonify({"error": "워드클라우드를 생성할 가사 데이터가 없습니다."}), 400

    try:
        image_url = generate_wordcloud_and_upload_to_gcs(lyrics, song_title, artist)
        return jsonify({"wordcloud_url": image_url})
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": "워드클라우드 생성 중 오류 발생"}), 500


# ────────────────────────────────
# Spotify OAuth 인증 후 리디렉션 받을 엔드포인트 추가 (06/05)


@app.route("/callback")
def spotify_callback():
    sp_oauth = SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
        scope="user-library-read",
    )
    session_code = request.args.get("code")
    if session_code:
        token_info = sp_oauth.get_access_token(session_code)
        return {"access_token": token_info["access_token"]}
    else:
        return "Authorization failed", 400


# ────────────────────────────────
# 헬스 체크 엔드포인트
@app.route("/health", methods=["GET"])
def health_check():
    """서버가 정상적으로 실행 중인지 간단히 확인"""
    return jsonify({"status": "ok"}), 200


# ────────────────────────────────
# 디버그 정보 엔드포인트
@app.route("/debug", methods=["GET"])
def debug_info():
    """서버의 상세한 내부 상태 정보 제공"""

    # 1. Firestore 연결 상태 확인
    try:
        # 간단한 데이터 읽기 시도를 통해 실제 연결 유효성을 검사한다.
        db.collection("user_playlists").limit(1).get()
        firestore_status = "connected"
    except Exception as e:
        firestore_status = f"disconnected - {str(e)}"

    # 2. 메모리 사용량 확인
    memory_usage = psutil.virtual_memory().percent

    # 3. 'failed_searches.log' 파일 최근 5줄 읽기
    failed_log_content = []
    try:
        with open("failed_searches.log", "r", encoding="utf-8") as f:
            # 파일의 마지막 라인부터 읽어서 최대 5줄을 저장한다.
            failed_log_content = deque(f, maxlen=5)
    except FileNotFoundError:
        failed_log_content = ["File not found."]
    except Exception as e:
        failed_log_content = [f"Error reading file: {str(e)}"]

    # 4. 최종 디버그 정보 조합
    debug_data = {
        "server_time": datetime.datetime.now().isoformat(),
        "firestore_status": firestore_status,
        "system_memory_usage_percent": memory_usage,
        "recent_requests": list(recent_requests),
        "failed_searches_log": list(failed_log_content),
    }

    return jsonify(debug_data)


# ────────────────────────────────
if __name__ == "__main__":
    # Cloud Run과 같은 관리형 환경에서는 gunicorn을 사용하므로,
    # 아래 host, port 설정은 로컬 테스트용이다.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
