import os
from flask import Flask
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

# 작성한 서비스 클래스 임포트
from .services.nlp_service import NLPService
from .services.music_service import MusicDataService
from .services.image_service import ImageService

# 블루프린트 임포트
from .controllers.quiz_controller import quiz_bp

# .env 로드
load_dotenv()


def create_app():
    app = Flask(__name__)

    # CORS 설정 (모든 출처 허용)
    CORS(app)

    # 1. Firebase 초기화 (앱 컨텍스트 밖에서 한 번만 수행)
    try:
        if not firebase_admin._apps:
            # 로컬 개발 환경: 서비스 계정 키 파일 사용 권장
            # 배포 환경(GCP): 기본 자격 증명 사용 (initialize_app() 인자 없음)
            cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            if cred_path and os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
            else:
                firebase_admin.initialize_app()
            print("✅ Firebase App initialized.")
    except Exception as e:
        print(f"❌ Firebase Init Error: {e}")

    # Firestore 클라이언트 생성
    db = firestore.client()

    # 2. 서비스 인스턴스 생성 및 앱에 부착 (Dependency Injection 효과)
    # 이렇게 하면 컨트롤러에서 current_app.nlp_service 형태로 접근 가능
    app.db = db

    # NLP 서비스 (모델 로딩 포함 - 시간이 조금 걸릴 수 있음)
    app.nlp_service = NLPService()

    # Music 서비스 (Spotify, Genius 클라이언트 포함)
    app.music_service = MusicDataService(db_client=db)

    # Image 서비스 (GCS 클라이언트 포함)
    app.image_service = ImageService()

    # 3. 블루프린트 등록 (라우팅 연결)
    app.register_blueprint(quiz_bp)

    return app
