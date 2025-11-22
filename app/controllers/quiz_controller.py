from datetime import datetime, timezone, timedelta
import uuid
import re
from flask import Blueprint, request, jsonify, current_app
from firebase_admin import firestore


# ────────────────────────────────
# 헬퍼 함수: Firestore에서 특정 곡을 찾는 중복 코드를 하나의 함수로 통합
def _get_song_data_from_firestore(doc_id: str, song_title: str) -> dict:
    """
    Firestore에서 특정 곡의 데이터를 찾아 반환하는 헬퍼 함수
    """
    db = current_app.db
    try:
        doc_ref = db.collection("user_playlists").document(doc_id)
        doc = doc_ref.get()

        if not doc.exists:
            return None  # 문서 없음

        playlist_data = doc.to_dict()
        tracks = playlist_data.get("tracks", [])

        for song in tracks:
            # clean_title 또는 original_title과 일치하는지 확인 (유연성 확보)
            if (song.get("clean_title") == song_title) or (
                song.get("original_title") == song_title
            ):
                return song

        return None  # 해당 곡을 찾지 못함

    except Exception as e:
        print(f"Error in helper function: {e}")
        return None


# ────────────────────────────────


def _id_generate():
    """
    id_postfix 생성
    """
    # 각 요청을 위한 고유 ID 생성
    quiz_id = str(uuid.uuid4())

    # 1. UTC+9 시간대 객체 정의 (9시간의 차이)
    # 이유: KST는 고정된 오프셋이므로, 별도의 외부 라이브러리 없이 표준 모듈로 충분하다.
    KST_TZ = timezone(timedelta(hours=9))

    # 2. UTC 시간 객체를 KST로 변환
    utc_now = datetime.now(timezone.utc)
    kst_now = utc_now.astimezone(KST_TZ)

    # 4. YYYY_MM_DD_HH_MM 형식으로 포맷팅
    kst_formatted = kst_now.strftime("%Y_%m_%d_%H_%M")

    # Request ID 생성 (플레이리스트ID + 타임스탬프 + uuid)
    id_postfix = f"{kst_formatted}_{quiz_id}"

    return id_postfix


# 기존 앱과의 호환성을 위해 url_prefix='' 설정 (루트 경로 사용)
quiz_bp = Blueprint("quiz", __name__, url_prefix="")


@quiz_bp.route("/health", methods=["GET"])
def health_check():
    """서버 상태 확인용 엔드포인트"""
    # 기존 앱이 /health를 호출하므로 경로 유지
    print("🩺 [Health Check] /health probe received by Flask app!")
    return jsonify({"status": "ok"}), 200


@quiz_bp.route("/crawl", methods=["POST"])
def crawl_playlist():
    """
    Spotify 플레이리스트 URL을 받아 가사를 수집
    기존 앱 요청 Body: {"playlist_url": "https://open.spotify.com/playlist/..."}
    기존 앱 응답: {"doc_id": "..."}
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request"}), 400

    playlist_url = data.get("playlist_url")
    if not playlist_url:
        return jsonify({"error": "Missing 'playlist_url'"}), 400

    # 1. URL에서 Playlist ID 추출 (정규식 사용)
    # 예: https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=...
    match = re.search(r"playlist/([a-zA-Z0-9]+)", playlist_url)
    if match:
        playlist_id = match.group(1)
    else:
        return jsonify({"error": "잘못된 Spotify 플레이리스트 URL입니다."}), 400

    # Request ID 생성
    id_postfix = _id_generate()
    request_id = f"{playlist_id}_{id_postfix}"
    client_ip = request.remote_addr
    # 프록시 환경을 고려한 실제 IP 확인 방법
    # client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)

    try:
        # MusicDataService 호출 (current_app을 통해 접근)
        result_id = current_app.music_service.fetch_and_save_playlist(
            playlist_id, request_id, client_ip
        )

        if result_id:
            # 기존 앱이 'doc_id'라는 키를 기다리므로 맞춰줌
            return jsonify({"doc_id": result_id}), 200
        else:
            return jsonify({"error": "Failed to fetch playlist"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@quiz_bp.route("/quizdata/<string:doc_id>", methods=["GET"])
def get_quizdata(doc_id):
    """
    Firestore 문서 ID를 기반으로 퀴즈 데이터를 생성하여 반환한다. (NLP 분석 수행)
    기존 앱은 이 API를 호출할 때 분석 결과를 기대함.
    따라서 여기서 NLP 분석이 안 되어 있다면 즉시 수행해야 함.
    """
    db = current_app.db
    try:
        doc_ref = db.collection("user_playlists").document(doc_id)
        doc = doc_ref.get()

        if not doc.exists:
            return jsonify({"error": "Document not found"}), 404

        playlist_data = doc.to_dict()
        tracks = playlist_data.get("tracks", [])

        quiz_result = []
        failed_songs = []  # 실패한 곡을 추적하기 위한 리스트
        needs_update = False

        # 트랙 순회하며 분석 및 결과 구성
        for song in tracks:
            try:
                title = song.get("clean_title", song.get("original_title"))
                artist = song.get("artist")
                lyrics = song.get("lyrics", "")
                if not lyrics.strip():
                    print(
                        f"Skipping song {song.get('clean_title')} due to empty lyrics."
                    )
                    continue

                # 분석된 데이터가 없으면 지금 분석 수행 (Lazy Analysis)
                if "summary" not in song or not song["summary"]:
                    summary, keywords = current_app.nlp_service.process_lyrics(
                        lyrics, title=title
                    )
                    song["summary"] = summary
                    song["keywords"] = keywords
                    needs_update = True  # DB 업데이트 필요 표시

                # 퀴즈 결과 리스트에 추가 (기존 앱이 기대하는 필드 포함)
                if song.get("summary") and song.get("keywords"):
                    quiz_result.append(
                        {
                            "title": title,
                            "artist": artist,
                            "summary": song["summary"],
                            "keywords": song["keywords"],
                            "lyrics": lyrics,
                        }
                    )
                else:
                    # 가사는 있으나 모델 분석에 실패한 경우
                    failed_songs.append(song.get("clean_title"))
                    print(
                        f"⚠️  Skipping song '{song.get('clean_title')}' due to analysis failure (empty result)."
                    )
            except:
                # --- [Robustness] 예상치 못한 오류 발생 시 ---
                # (예: song 딕셔너리 포맷이 깨진 경우)
                failed_songs.append(song.get("clean_title", "Unknown Title"))
                print(
                    f"❌  [Quizdata Error] Critical error processing song. Skipping. Error: {e}"
                )
                continue  # 이 곡을 건너뛰고 다음 곡으로 계속 진행

        # 분석을 새로 수행했다면 DB에 저장 (다음 요청을 빠르게 하기 위함)
        if needs_update:
            doc_ref.update(
                {
                    "tracks": tracks,
                    "status": "analyzed",
                    "analyzedAt": firestore.SERVER_TIMESTAMP,
                }
            )

        return jsonify(quiz_result), 200

    except Exception as e:
        print(f"Quizdata 생성 중 외부 오류: {e}")
        return jsonify({"Quizdata error": str(e)}), 500


@quiz_bp.route("/wordcloud/<string:doc_id>/<string:song_title>", methods=["GET"])
def get_wordcloud(doc_id, song_title):
    """
    Firestore에서 특정 곡의 정보를 가져와 워드클라우드를 생성하고 URL을 반환
    """
    try:
        # 1. 헬퍼 함수를 사용해 곡 데이터 조회
        song = _get_song_data_from_firestore(doc_id, song_title)

        if not song:
            return jsonify({"error": "Song not found"}), 404

        lyrics = song.get("lyrics", "")
        artist = song.get("artist", "Unknown")

        # 2. ImageService 호출
        wc_url = current_app.image_service.generate_and_upload(
            lyrics, song_title, artist
        )

        if wc_url:
            return jsonify({"wordcloud_url": wc_url}), 200
        else:
            return jsonify({"error": "Failed to generate wordcloud"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@quiz_bp.route("/analyze/<string:doc_id>/<string:song_title>", methods=["GET"])
def analyze_single_song(doc_id, song_title):
    """
    [기존 호환] 개별 곡 분석 결과 반환 (혹시 앱에서 사용할 경우를 대비)
    """
    try:
        # 1. 헬퍼 함수를 사용해 곡 데이터 조회
        track = _get_song_data_from_firestore(doc_id, song_title)

        if not track:
            return jsonify({"error": "Song not found"}), 404

        # 2. NLP 서비스 호출 (이미 분석된 경우 DB값을 쓸 수도 있지만, 여기선 강제 분석 로직 유지)
        summary, keywords = current_app.nlp_service.process_lyrics(
            track["lyrics"], song_title
        )
        return jsonify({"summary": summary, "keywords": keywords})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
