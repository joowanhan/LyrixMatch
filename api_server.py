# api_server.py (Refactored)

from spotipy.oauth2 import SpotifyOAuth
from flask import request, redirect
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import os

# 모니터링 엔드포인트 를 위한 모듈 추가
# 최근 요청 기록을 효율적으로 관리하기 위한 collections.deque
from collections import deque
import datetime

# --- 모듈 임포트 ---
# 각 모듈의 역할에 맞는 함수만 가져온다.
# from get_lyrics_save_firestore import process_playlist_and_save_to_firestore
# from lyrics_analyzer_firestore import process_lyrics
# from wc import generate_wordcloud_and_upload_to_gcs
import firebase_admin
from firebase_admin import credentials, firestore

# .env 로드 및 Firebase 앱 초기화
load_dotenv()


# [변경] Flask 앱 생성 부분을 함수로 감싼다 (앱 팩토리 패턴)
def create_app():
    app = Flask(__name__)
    CORS(app)  # CORS 설정은 app 생성 직후

    # # --- 함수 내부에서 Firebase 초기화 및 db 생성 ---
    # try:
    #     if not firebase_admin._apps:
    #         cred = credentials.ApplicationDefault()
    #         firebase_admin.initialize_app(cred)
    #         print("✅ Firebase App initialized successfully inside create_app.")
    #     # else: # 이미 초기화된 경우
    #     #     print("ℹ️ Firebase App already initialized.")
    # except Exception as e:
    #     print(f"❌ Firebase App initialization failed inside create_app: {e}")

    try:
        if not firebase_admin._apps:
            # 인수 없이 초기화
            # 1. 로컬: GOOGLE_APPLICATION_CREDENTIALS 환경 변수(.env)를 찾아 JSON 키로 인증
            # 2. Cloud Run: 환경 변수가 없으므로 ADC를 사용해 서비스 계정으로 자동 인증
            firebase_admin.initialize_app()
            print("✅ Firebase App initialized successfully (from module).")
    except Exception as e:
        print(f"❌ Firebase App initialization failed in module: {e}")

    # Firestore 클라이언트는 함수 내에서 또는 전역으로 접근 가능하게 설정
    # 여기서는 간단하게 전역 변수로 설정 (다른 방법도 가능)
    global db
    db = firestore.client()
    # -------------------------------------------------

    # ----- 최근 요청 deque는 그대로 유지 -----
    global recent_requests
    recent_requests = deque(maxlen=5)
    # ----------------------------------------

    return app  # 생성된 Flask 앱 객체 반환


# 전역 변수로 db 선언 (create_app 내부에서 할당됨)
db = None
recent_requests = deque(maxlen=5)  # 초기화

# Flask 앱 인스턴스 생성 (Gunicorn이 이 'app' 변수를 찾음)
app = create_app()


# ──────────────────────────────────────────────────
# ───── 로깅을 위한 데코레이터 추가 ─────
# 모든 요청이 실행되기 전에 로그를 기록한다.
@app.before_request
def log_request_info():
    global recent_requests
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
    global db
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
# @app.route("/crawl", methods=["POST"])
# def crawl_playlist():
#     from get_lyrics_save_firestore import process_playlist_and_save_to_firestore

#     data = request.get_json()
#     playlist_url = data.get("playlist_url")
#     if not playlist_url:
#         return jsonify({"error": "Missing playlist_url"}), 400

#     try:
#         # Firestore에 저장 후 고유 문서 ID를 반환받는다.
#         doc_id = process_playlist_and_save_to_firestore(playlist_url)
#         if doc_id:
#             # 클라이언트에게 이 ID를 전달한다.
#             return jsonify({"doc_id": doc_id}), 200
#         else:
#             return jsonify({"error": "플레이리스트 처리 중 서버 오류 발생"}), 500
#     except Exception as e:
#         print(f"Error during crawl: {e}")  # 디버깅을 위한 로그 추가
#         return jsonify({"error": f"처리 중 오류: {str(e)}"}), 500

# api_server.py에 이 코드로 교체 (또는 추가)


@app.route("/crawl", methods=["POST"])
def crawl_playlist():
    # 1. 비즈니스 로직 함수 임포트
    from get_lyrics_save_firestore import process_playlist_and_save_to_firestore

    # 2. 클라이언트 요청 데이터 유효성 검사 (JSON 본문)
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request: Missing JSON body"}), 400

    # 3. 클라이언트 요청 데이터 유효성 검사 (필수 키)
    playlist_url = data.get("playlist_url")
    if not playlist_url:
        return jsonify({"error": "Invalid request: Missing 'playlist_url' key"}), 400

    try:
        # 4. 핵심 비즈니스 로직 실행
        # (이 함수 내부에서 URL 형식 검사(ValueError) 및 Spotipy/Genius/Firestore 작업 수행)
        doc_id = process_playlist_and_save_to_firestore(playlist_url)

        # 5. 로직 실행 후 결과 검사 (성공)
        if doc_id:
            return jsonify({"doc_id": doc_id}), 200

        # 6. 로직 실행 후 결과 검사 (알 수 없는 실패)
        else:
            # 예외는 없었으나, 함수가 None을 반환한 경우 (e.g., Firestore 저장 실패)
            print(
                "Error during crawl: process_playlist_and_save_to_firestore returned None"
            )
            return (
                jsonify({"error": "플레이리스트 처리 중 서버 오류 발생 (Code: N-1)"}),
                500,
            )

    # 7. 예외 처리 (클라이언트 입력 오류)
    except ValueError as ve:
        # process_playlist_and_save_to_firestore가 "잘못된 URL"로 raise한 경우
        #
        print(f"Client Error during crawl: {ve}")
        # 500 (서버 오류)가 아닌 400 (클라이언트 요청 오류) 반환
        return jsonify({"error": f"잘못된 입력: {str(ve)}"}), 400

    # 8. 예외 처리 (서버 내부 오류)
    except Exception as e:
        # Spotipy API 인증 오류 (Invalid base62 id 등), Genius 타임아웃,
        # Firestore API 비활성화 등 예측하지 못한 모든 '서버 측' 오류
        print(f"Internal Server Error during crawl: {e}")  # 디버깅을 위한 로그
        return jsonify({"error": f"서버 내부 처리 중 오류: {str(e)}"}), 500


# ────────────────────────────────


@app.route("/analyze/<string:doc_id>/<string:song_title>", methods=["GET"])
def analyze_song(doc_id, song_title):
    """Firestore에서 특정 곡의 가사를 가져와 요약 및 키워드를 반환"""
    from lyrics_analyzer_firestore import process_lyrics

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

    from lyrics_analyzer_firestore import process_lyrics

    global db
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
    from wc import generate_wordcloud_and_upload_to_gcs

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
    # [추가] Cloud Run 시작 프로브가 이 함수를 호출하는지 확인하기 위한 로그
    print("🩺 [Health Check] /health probe received by Flask app!")
    return jsonify({"status": "ok"}), 200


# ────────────────────────────────
# 디버그 정보 엔드포인트
@app.route("/debug", methods=["GET"])
def debug_info():
    """서버의 상세한 내부 상태 정보 제공"""

    # 시스템의 자원(메모리 등)을 확인하기 위한 psutil
    # import psutil

    global db
    global recent_requests
    # 1. Firestore 연결 상태 확인
    try:
        # 간단한 데이터 읽기 시도를 통해 실제 연결 유효성을 검사한다.
        db.collection("user_playlists").limit(1).get()
        firestore_status = "connected"
    except Exception as e:
        firestore_status = f"disconnected - {str(e)}"

    # 2. 메모리 사용량 확인
    # memory_usage = psutil.virtual_memory().percent

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
        # "system_memory_usage_percent": memory_usage,
        "recent_requests": list(recent_requests),
        "failed_searches_log": list(failed_log_content),
    }

    return jsonify(debug_data)


# --- [임시 디버그용] ---
@app.route("/debug-env", methods=["GET"])
def debug_env():
    # Secret Manager에서 참조한 키들
    spotify_id = os.environ.get("SPOTIFY_CLIENT_ID")
    spotify_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    genius_token = os.environ.get("GENIUS_TOKEN")

    # .get()의 결과가 None인지, 아니면 실제 값이 문자열로 들어왔는지 확인
    return (
        jsonify(
            {
                "SPOTIFY_CLIENT_ID_IS_SET": spotify_id is not None
                and len(spotify_id) > 0,
                "SPOTIFY_CLIENT_SECRET_IS_SET": spotify_secret is not None
                and len(spotify_secret) > 0,
                "GENIUS_TOKEN_IS_SET": genius_token is not None
                and len(genius_token) > 0,
            }
        ),
        200,
    )


# --- [ /임시 디버그용] ---


# --- [신규] Spotify 인증 테스트용 디버그 엔드포인트 ---
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import os


@app.route("/debug-spotify", methods=["GET"])
def debug_spotify_connection():
    try:
        # 1. 환경 변수(API 키)를 불러온다.
        client_id = os.environ.get("SPOTIFY_CLIENT_ID")
        client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")

        if not client_id or not client_secret:
            return (
                jsonify(
                    {
                        "status": "failed",
                        "message": "Error: SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET is not set in environment.",
                    }
                ),
                400,
            )

        # 2. Spotipy 클라이언트 인증을 시도한다. (Client Credentials Flow)
        auth_manager = SpotifyClientCredentials(
            client_id=client_id, client_secret=client_secret
        )
        sp = spotipy.Spotify(auth_manager=auth_manager)

        # 3. 인증 테스트를 위해 실제 API를 호출한다. (가장 가벼운 요청)
        playlist_id = "295349rZbeojC5YHpA5WlV"
        test_call = sp.playlist_items(playlist_id, fields="items(track(name))", limit=1)

        # 4. API 호출에 성공하면 인증 성공
        first_track_name = test_call["items"][0]["track"]["name"]
        return (
            jsonify(
                {
                    "status": "success",
                    "message": "Spotify API authentication successful.",
                    "test_playlist_name": "song1test",
                    "fetched_track_name": first_track_name,
                }
            ),
            200,
        )

    except Exception as e:
        # 5. 인증 실패 또는 API 호출 실패 시
        print(f"[Debug Spotify Error] {e}")
        return (
            jsonify(
                {"status": "failed", "message": f"Spotify connection failed: {str(e)}"}
            ),
            500,
        )


# --- [ /신규 디버그 엔드포인트 ] ---

# ────────────────────────────────
if __name__ == "__main__":
    # Cloud Run과 같은 관리형 환경에서는 gunicorn을 사용하므로,
    # 아래 host, port 설정은 로컬 테스트용이다.
    # app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

    # [변경] Flask의 app.run() 대신 waitress.serve()를 사용
    from waitress import serve

    # Cloud Run이 $PORT 환경 변수를 주입한다.
    port = int(os.environ.get("PORT", 8080))

    print(f"🔄 Starting Waitress server on port {port}...")

    # app 객체는 파일 중간의 create_app() 호출로 이미 생성되어 있음
    serve(app, host="0.0.0.0", port=port)
