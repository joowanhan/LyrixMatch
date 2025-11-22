import os
from waitress import serve

# HuggingFace Tokenizers 병렬 처리 경고 끄기 (Deadlock 방지)
os.environ["TOKENIZERS_PARALLELISM"] = "false"
from app import create_app

# 앱 팩토리를 통해 앱 생성
app = create_app()


if __name__ == "__main__":
    # Cloud Run 등에서는 PORT 환경변수를 사용함
    port = int(os.environ.get("PORT", 8080))

    print(f"🚀 Starting Waitress Production Server on port {port}...")
    # 디버그 모드는 개발 중에만 True, 운영 시 False
    # app.run(host="0.0.0.0", port=port, debug=True)

    # 배포 -  app.run() 대신 serve() 사용
    serve(app, host="0.0.0.0", port=port)
