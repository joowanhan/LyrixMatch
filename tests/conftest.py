# 테스트 전반에 걸쳐 재사용되는 객체(예: Flask 앱, 가짜 DB 등)를 정의하는 곳
# 가짜 앱과 가짜 DB, 가짜 서비스(Mock)
import pytest
from unittest.mock import MagicMock
from app import create_app


@pytest.fixture
def mock_db():
    """Firestore 클라이언트를 흉내 내는 Mock 객체"""
    return MagicMock()


@pytest.fixture
def app(mock_db):
    """테스트용 Flask 앱 생성"""
    # 실제 앱 팩토리 실행
    app = create_app()
    app.config.update(
        {
            "TESTING": True,  # 테스트 모드 활성화
        }
    )

    # [핵심] 실제 DB 대신 Mock DB 주입
    app.db = mock_db

    # [핵심] 서비스 레이어도 Mock으로 교체 (테스트 속도 향상 및 외부 의존성 제거)
    app.music_service = MagicMock()
    app.nlp_service = MagicMock()
    app.image_service = MagicMock()

    yield app


@pytest.fixture
def client(app):
    """API 요청을 보낼 수 있는 가상 클라이언트"""
    return app.test_client()
