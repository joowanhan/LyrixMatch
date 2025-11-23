# 통합 테스트의 목표
# API 엔드포인트(/crawl, /quizdata)를 호출했을 때, 컨트롤러가 파라미터를 잘 받고, 서비스를 호출한 뒤, 올바른 JSON 응답을 내려주는지 확인
# URL 호출 시 컨트롤러가 서비스를 잘 부르고 응답을 잘 주는지 확인
# 실제 AI 모델은 돌리지 않고 Mock 결과를 사용

import json
from unittest.mock import MagicMock


def test_health_check(client):
    """/health 엔드포인트 테스트"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_crawl_playlist_success(client, app):
    """
    POST /crawl 요청 시 MusicService가 호출되고
    정상적으로 doc_id를 반환하는지 테스트
    """
    # 1. Mock 설정: MusicService가 성공적으로 ID를 반환한다고 가정
    app.music_service.fetch_and_save_playlist.return_value = "test_doc_id_123"

    # 2. API 요청
    payload = {"playlist_url": "http://spotify.com/playlist/123"}
    response = client.post(
        "/crawl", data=json.dumps(payload), content_type="application/json"
    )

    # 3. 검증
    assert response.status_code == 200
    assert response.json == {"doc_id": "test_doc_id_123"}

    # 실제로 서비스 메서드가 호출되었는지 확인 (파라미터 검증)
    app.music_service.fetch_and_save_playlist.assert_called_once()


def test_quizdata_lazy_analysis(client, app):
    """
    GET /quizdata 요청 시 분석 안 된 곡이 있으면
    NLPService를 호출하여 분석을 수행하는지(Lazy Analysis) 테스트
    """
    # 1. Mock DB 설정: 트랙 데이터를 반환하도록 설정
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        "tracks": [
            {
                "clean_title": "Song A",
                "artist": "Artist A",
                "lyrics": "La La La",
                # summary가 없음 -> 분석 필요
            }
        ]
    }
    app.db.collection().document().get.return_value = mock_doc

    # 2. Mock NLP Service 설정
    app.nlp_service.process_lyrics.return_value = ("요약문", ["키워드1", "키워드2"])

    # 3. API 요청
    response = client.get("/quizdata/test_doc_id_123")

    # 4. 검증
    assert response.status_code == 200
    data = response.json
    assert len(data) == 1
    assert data[0]["summary"] == "요약문"

    # NLP 서비스가 호출되었는지 확인 (Lazy Analysis 작동 여부)
    app.nlp_service.process_lyrics.assert_called_once()
