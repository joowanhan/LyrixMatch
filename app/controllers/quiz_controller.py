import uuid
from flask import Blueprint, request, jsonify, current_app
from firebase_admin import firestore
import time
from datetime import datetime, timezone, timedelta

# Blueprint 정의
quiz_bp = Blueprint("quiz", __name__, url_prefix="/api")


@quiz_bp.route("/health", methods=["GET"])
def health_check():
    """서버 상태 확인용 엔드포인트"""
    return jsonify({"status": "ok", "message": "Server is running"}), 200


@quiz_bp.route("/playlist", methods=["POST"])
def fetch_playlist():
    """
    [1단계] Spotify 플레이리스트 ID를 받아 가사를 수집하고 Firestore에 저장
    """
    data = request.json
    playlist_id = data.get("playlistId")

    if not playlist_id:
        return jsonify({"error": "playlistId is required"}), 400

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
    request_id = f"{playlist_id}_{kst_formatted}_{quiz_id}"
    client_ip = request.remote_addr
    # 프록시 환경을 고려한 실제 IP 확인 방법
    # client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)

    try:
        # MusicDataService 호출 (current_app을 통해 접근)
        result_id = current_app.music_service.fetch_and_save_playlist(
            playlist_id, request_id, client_ip
        )

        if result_id:
            return (
                jsonify(
                    {
                        "status": "success",
                        "message": "Playlist fetched and saved.",
                        "requestId": result_id,
                    }
                ),
                200,
            )
        else:
            return jsonify({"error": "Failed to fetch playlist"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@quiz_bp.route("/analyze", methods=["POST"])
def analyze_playlist():
    """
    [2단계] 수집된 가사 데이터(Firestore)를 불러와 NLP 분석 및 워드클라우드 생성
    """
    data = request.json
    request_id = data.get("requestId")

    if not request_id:
        return jsonify({"error": "requestId is required"}), 400

    db = current_app.db

    try:
        # 1. Firestore에서 데이터 가져오기
        doc_ref = db.collection("user_playlists").document(request_id)
        doc = doc_ref.get()

        if not doc.exists:
            return jsonify({"error": "Document not found"}), 404

        playlist_data = doc.to_dict()
        tracks = playlist_data.get("tracks", [])

        analyzed_tracks = []

        # 2. 각 트랙 순회하며 분석 수행
        for track in tracks:
            # 이미 처리된 결과가 있으면 스킵 가능 (필요 시 로직 추가)
            title = track.get("clean_title", track.get("original_title"))
            artist = track.get("artist")
            lyrics = track.get("lyrics", "")

            # A. NLP 분석 (요약 및 키워드)
            summary, keywords = current_app.nlp_service.process_lyrics(
                lyrics, title=title
            )

            # B. 워드클라우드 생성 및 업로드
            wc_url = current_app.image_service.generate_and_upload(
                lyrics, title, artist
            )

            # C. 결과 업데이트
            track["summary"] = summary
            track["keywords"] = keywords
            track["wordcloud_url"] = wc_url

            analyzed_tracks.append(track)

        # 3. 분석 결과 Firestore에 다시 업데이트
        doc_ref.update(
            {
                "tracks": analyzed_tracks,
                "status": "analyzed",
                "analyzedAt": firestore.SERVER_TIMESTAMP,
            }
        )

        return (
            jsonify(
                {
                    "status": "success",
                    "message": "Analysis complete",
                    "trackCount": len(analyzed_tracks),
                }
            ),
            200,
        )

    except Exception as e:
        print(f"Analysis Error: {e}")
        return jsonify({"error": str(e)}), 500
