# api_server.py (Refactored for Eager Loading & Robustness)

from spotipy.oauth2 import SpotifyOAuth
from flask import request, redirect
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import os

# 모니터링 엔드포인트 를 위한 모듈 추가
from collections import deque
import datetime

# --- 모듈 임포트 ---
import firebase_admin
from firebase_admin import credentials, firestore

# .env 로드
load_dotenv()

# --- [Eager Loading] 1. 모델 로더 임포트 ---
# (이 시점에서 lyrics_analyzer_firestore.py 파일이 로드됨)
try:
    from lyrics_analyzer_firestore import load_all_models, process_lyrics
except ImportError:
    print("❌ Critical Error: Failed to import from lyrics_analyzer_firestore.")
    # 실제 운영 환경에서는 여기서 서버가 중단되어야 할 수도 있음
    load_all_models = None
    process_lyrics = None
# ---------------------------------------------


# [변경] Flask 앱 생성 부분을 함수로 감싼다 (앱 팩토리 패턴)
def create_app():
    app = Flask(__name__)
    CORS(app)  # CORS 설정은 app 생성 직후

    try:
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
            print("✅ Firebase App initialized successfully (from module).")
    except Exception as e:
        print(f"❌ Firebase App initialization failed in module: {e}")

    global db
    db = firestore.client()
    # -------------------------------------------------

    global recent_requests
    recent_requests = deque(maxlen=5)
    # ----------------------------------------

    return app  # 생성된 Flask 앱 객체 반환


# 전역 변수로 db 선언 (create_app 내부에서 할당됨)
db = None
recent_requests = deque(maxlen=5)  # 초기화

# Flask 앱 인스턴스 생성 (Gunicorn이 이 'app' 변수를 찾음)
app = create_app()

# --- [Eager Loading] 2. 모델 로더 즉시 실행 ---
# Gunicorn/Waitress가 이 파일을 로드하는 시점에
# create_app()이 실행된 직후, 모델 로드를 동기적으로 수행한다.
# Cloud Run이 트래픽을 받기 전에 모든 모델이 로드된다.
if load_all_models:
    print("--- 🚀 Initializing AI Models (Eager Loading) ---")
    load_all_models()
    print("--- ✅ AI Models Ready. Starting Server... ---")
else:
    print("--- ⚠️ AI Model loader not found. Server starting without AI models. ---")
# -------------------------------------------------


# ──────────────────────────────────────────────────
# ───── 로깅을 위한 데코레이터 추가 ─────
@app.before_request
def log_request_info():
    global recent_requests
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
        if song.get("clean_title") == song_title:
            return song

    return None  # 해당 곡을 찾지 못함


# ────────────────────────────────
# API 엔드포인트


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
        doc_id = process_playlist_and_save_to_firestore(playlist_url)

        # 5. 로직 실행 후 결과 검사 (성공)
        if doc_id:
            return jsonify({"doc_id": doc_id}), 200

        # 6. 로직 실행 후 결과 검사 (알 수 없는 실패)
        else:
            print(
                "Error during crawl: process_playlist_and_save_to_firestore returned None"
            )
            return (
                jsonify({"error": "플레이리스트 처리 중 서버 오류 발생 (Code: N-1)"}),
                500,
            )

    # 7. 예외 처리 (클라이언트 입력 오류)
    except ValueError as ve:
        print(f"Client Error during crawl: {ve}")
        return jsonify({"error": f"잘못된 입력: {str(ve)}"}), 400

    # 8. 예외 처리 (서버 내부 오류)
    except Exception as e:
        print(f"Internal Server Error during crawl: {e}")
        return jsonify({"error": f"서버 내부 처리 중 오류: {str(e)}"}), 500


# ────────────────────────────────


@app.route("/analyze/<string:doc_id>/<string:song_title>", methods=["GET"])
def analyze_song(doc_id, song_title):
    """Firestore에서 특정 곡의 가사를 가져와 요약 및 키워드를 반환"""
    # from lyrics_analyzer_firestore import process_lyrics (전역 임포트로 변경됨)

    song_data = _get_song_data_from_firestore(doc_id, song_title)
    if not song_data:
        return jsonify({"error": "해당 곡을 찾을 수 없습니다."}), 404

    lyrics = song_data.get("lyrics_processed", "")
    if not lyrics:
        return jsonify({"error": "분석할 가사 데이터가 없습니다."}), 400
    title = song_data.get("clean_title") or song_data.get("original_title") or ""

    # [Robustness] process_lyrics 내부에 이미 try-except가 있으므로
    # 여기서는 반환된 값이 비어있는지만 확인하면 된다.
    summary, keywords = process_lyrics(lyrics, title)

    if not summary and not keywords:
        # 모델이 분석에 실패했으나, 서버가 멈추지 않고 400 (Bad Request) 대신
        # 200 (OK) 또는 202 (Accepted)와 함께 "분석 실패" 메시지를 반환할 수도 있음
        return jsonify({"error": "가사 분석에 실패했으나 서버는 정상입니다."}), 202

    return jsonify({"summary": summary, "keywords": keywords})


# ────────────────────────────────


@app.route("/quizdata/<string:doc_id>", methods=["GET"])
def get_quizdata_from_firestore(doc_id):
    """
    Firestore 문서 ID를 기반으로 퀴즈 데이터를 생성하여 반환한다.
    [Robustness] 개별 곡 분석 실패 시 해당 곡을 제외하고 퀴즈를 생성한다.
    """

    # from lyrics_analyzer_firestore import process_lyrics (전역 임포트로 변경됨)
    global db
    try:
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
        failed_songs = []  # 실패한 곡을 추적하기 위한 리스트

        for song in tracks:
            try:  # --- [Robustness] 1. 개별 곡 처리용 try-except ---
                lyrics = song.get("lyrics_processed", "")
                if not lyrics.strip():
                    # print(f"Skipping song {song.get('clean_title')} due to empty lyrics.")
                    continue
                title = song.get("clean_title") or song.get("original_title") or ""

                # Eager Loading으로 process_lyrics는 매우 빠르게 실행됨
                summary, keywords = process_lyrics(lyrics, title)

                # [Robustness] 2. 모델이 분석에 성공한 경우에만 퀴즈에 추가
                # (process_lyrics가 실패 시 (summary="", keywords=[])를 반환)
                if summary and keywords:
                    quiz_result.append(
                        {
                            "title": song.get("clean_title"),
                            "artist": song.get("artist"),
                            "summary": summary,
                            "keywords": keywords,
                            "lyrics": lyrics,
                        }
                    )
                else:
                    # 가사는 있으나 모델 분석에 실패한 경우
                    failed_songs.append(song.get("clean_title"))
                    print(
                        f"⚠️  Skipping song '{song.get('clean_title')}' due to analysis failure (empty result)."
                    )

            except Exception as e:
                # --- [Robustness] 3. 예상치 못한 오류 발생 시 ---
                # (예: song 딕셔너리 포맷이 깨진 경우)
                failed_songs.append(song.get("clean_title", "Unknown Title"))
                print(
                    f"❌  [Quizdata Error] Critical error processing song. Skipping. Error: {e}"
                )
                continue  # 이 곡을 건너뛰고 다음 곡으로 계속 진행

        # --- [Robustness] 4. 최종 결과 반환 ---
        if not quiz_result and failed_songs:
            # 모든 곡이 분석에 실패한 경우
            return (
                jsonify(
                    {
                        "error": "모든 곡의 가사 분석에 실패했습니다.",
                        "failed_songs": failed_songs,
                    }
                ),
                500,
            )

        if not quiz_result:
            # 곡은 있었으나 가사가 모두 비어있던 경우
            return jsonify({"error": "플레이리스트에 분석할 가사가 없습니다."}), 404

        # 1곡이라도 성공했다면, 성공한 곡들로만 퀴즈 반환
        return jsonify(quiz_result)

    except Exception as e:
        print(f"Quizdata 생성 중 외부 오류: {e}")
        return jsonify({"error": "퀴즈 데이터 생성 중 심각한 오류 발생"}), 500


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
    print("🩺 [Health Check] /health probe received by Flask app!")
    return jsonify({"status": "ok"}), 200


# ────────────────────────────────
# 디버그 정보 엔드포인트
@app.route("/debug", methods=["GET"])
def debug_info():
    """서버의 상세한 내부 상태 정보 제공"""

    global db
    global recent_requests
    # 1. Firestore 연결 상태 확인
    try:
        db.collection("user_playlists").limit(1).get()
        firestore_status = "connected"
    except Exception as e:
        firestore_status = f"disconnected - {str(e)}"

    # 2. 'failed_searches.log' 파일 최근 5줄 읽기
    failed_log_content = []
    try:
        with open("failed_searches.log", "r", encoding="utf-8") as f:
            failed_log_content = deque(f, maxlen=5)
    except FileNotFoundError:
        failed_log_content = ["File not found."]
    except Exception as e:
        failed_log_content = [f"Error reading file: {str(e)}"]

    # 3. 최종 디버그 정보 조합
    debug_data = {
        "server_time": datetime.datetime.now().isoformat(),
        "firestore_status": firestore_status,
        "recent_requests": list(recent_requests),
        "failed_searches_log": list(failed_log_content),
    }

    return jsonify(debug_data)


# --- [임시 디버그용] ---
@app.route("/debug-env", methods=["GET"])
def debug_env():
    spotify_id = os.environ.get("SPOTIFY_CLIENT_ID")
    spotify_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    genius_token = os.environ.get("GENIUS_TOKEN")

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

# ────────────────────────────────
# --- [신규] Spotify 인증 테스트용 디버그 엔드포인트 ---
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials


@app.route("/debug-spotify", methods=["GET"])
def debug_spotify_connection():
    try:
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

        auth_manager = SpotifyClientCredentials(
            client_id=client_id, client_secret=client_secret
        )
        sp = spotipy.Spotify(auth_manager=auth_manager)
        playlist_id = "295349rZbeojC5YHpA5WlV"
        test_call = sp.playlist_items(playlist_id, fields="items(track(name))", limit=1)
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
    # 이 블록은 'python api_server.py'로 직접 실행할 때만 동작
    # (Gunicorn/Waitress는 이 블록을 실행하지 않음)
    from waitress import serve

    port = int(os.environ.get("PORT", 8080))

    print(f"🔄 Starting Waitress server FOR LOCAL TEST on port {port}...")

    # 로컬 테스트 시에도 Eager Loading이 이미 위에서 실행되었음
    serve(app, host="0.0.0.0", port=port)
