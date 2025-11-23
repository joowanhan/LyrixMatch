# 단위 테스트
# 목표: 외부 API(Spotify, Genius)나 DB가 없어도 비즈니스 로직(Service)이 정상적으로 작동하는지 검증
# 로직(가사 전처리 등)이 맞는지 확인 외부 API는 Mocking

import pytest
from unittest.mock import MagicMock
from app.services.music_service import MusicDataService


def test_music_service_initialization():
    """MusicDataService가 정상적으로 생성되는지 테스트"""
    mock_db = MagicMock()
    service = MusicDataService(mock_db)
    assert service.db == mock_db


def test_process_single_track_logic(mocker):
    """
    _process_single_track 메서드가 Spotify 데이터를 받아
    우리가 원하는 포맷으로 잘 변환하는지 테스트 (외부 API 호출 Mocking)
    """
    # 1. 준비 (Arrange)
    mock_db = MagicMock()
    service = MusicDataService(mock_db)

    # Genius API 클라이언트가 있다고 가정
    service.genius = MagicMock()

    # Genius 검색 결과 Mocking
    mock_song = MagicMock()
    mock_song.lyrics = "Song Title Lyrics\n[Verse 1]\nHello world"
    service.genius.search_song.return_value = mock_song

    # Spotify에서 받은 샘플 데이터 (Input)
    sample_item = {
        "track": {
            "name": "Test Song",
            "artists": [{"name": "Test Artist"}],
            "album": {"images": [{"url": "http://image.url"}]},
        }
    }

    # 2. 실행 (Act)
    result = service._process_single_track(sample_item)

    # 3. 검증 (Assert)
    assert result is not None
    assert result["original_title"] == "Test Song"
    assert result["artist"] == "Test Artist"
    assert result["album_art"] == "http://image.url"
    # 검증: 헤더와 태그가 제거되고 본문만 남았는지 확인
    assert "Song Title Lyrics" not in result["lyrics"]  # 헤더 삭제 확인
    assert "[Verse 1]" not in result["lyrics"]  # 태그 삭제 확인
    assert "Hello world" in result["lyrics"]  # 본문 유지 확인
