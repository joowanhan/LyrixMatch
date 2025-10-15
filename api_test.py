# api_test.py

import requests
import json
import time

# --- 테스트 설정 ---
# 로컬에서 실행 중인 Flask 서버의 주소
BASE_URL = "http://127.0.0.1:8080"

# 테스트에 사용할 Spotify 플레이리스트 URL (자신이 사용하는 플레이리스트로 변경 가능)
TEST_PLAYLIST_URL = "https://open.spotify.com/playlist/0BLpwcj2ShVelGnbsmH7lW"


def run_api_tests():
    """API 엔드포인트 테스트를 순차적으로 실행"""
    print("🚀 LyrixMatch API 서버 로컬 테스트를 시작합니다.")
    print(f"대상 서버: {BASE_URL}")
    print("-" * 50)

    try:
        # 1단계: /crawl 엔드포인트 테스트
        print("1️⃣ [POST /crawl] 플레이리스트 가사 수집 테스트 중...")
        crawl_response = requests.post(
            f"{BASE_URL}/crawl",
            headers={"Content-Type": "application/json"},
            json={"playlist_url": TEST_PLAYLIST_URL},
        )
        print(f"   -> Status Code: {crawl_response.status_code}")

        if crawl_response.status_code != 200:
            print("❌ Crawl 테스트 실패. 서버 로그를 확인하세요.")
            print(f"   -> 응답 내용: {crawl_response.text}")
            return

        crawl_data = crawl_response.json()
        doc_id = crawl_data.get("playlist_doc_id")

        if not doc_id:
            print("❌ 응답에서 'playlist_doc_id'를 찾을 수 없습니다.")
            return

        print(f"✅ Crawl 테스트 성공! (Firestore 문서 ID: {doc_id})")
        print("-" * 50)

        # Firestore에 데이터가 완전히 저장될 때까지 잠시 대기
        time.sleep(2)

        # 2단계: /quizdata 엔드포인트 테스트
        print(f"2️⃣ [GET /quizdata/{doc_id}] 퀴즈 데이터 요청 테스트 중...")
        quiz_response = requests.get(f"{BASE_URL}/quizdata/{doc_id}")
        print(f"   -> Status Code: {quiz_response.status_code}")

        if quiz_response.status_code != 200:
            print("❌ Quizdata 테스트 실패.")
            print(f"   -> 응답 내용: {quiz_response.text}")
            return

        quiz_data = quiz_response.json()
        if not quiz_data or not isinstance(quiz_data, list):
            print("❌ 퀴즈 데이터가 비어있거나 올바른 형식이 아닙니다.")
            return

        song_count = len(quiz_data)
        first_song = quiz_data[0]
        song_title = first_song.get("title")

        print(f"✅ Quizdata 테스트 성공! ({song_count}개의 곡 데이터 수신)")
        print(f"   -> 다음 테스트에 사용할 곡: '{song_title}'")
        print("-" * 50)

        # 3단계: /analyze 엔드포인트 테스트
        print(f"3️⃣ [GET /analyze/{doc_id}/{song_title}] 가사 분석 테스트 중...")
        analyze_response = requests.get(f"{BASE_URL}/analyze/{doc_id}/{song_title}")
        print(f"   -> Status Code: {analyze_response.status_code}")

        if analyze_response.status_code != 200:
            print("❌ Analyze 테스트 실패.")
            print(f"   -> 응답 내용: {analyze_response.text}")
        else:
            print("✅ Analyze 테스트 성공!")
            # print(json.dumps(analyze_response.json(), indent=2, ensure_ascii=False))
        print("-" * 50)

        # 4단계: /wordcloud 엔드포인트 테스트
        print(
            f"4️⃣ [GET /wordcloud/{doc_id}/{song_title}] 워드클라우드 생성 테스트 중..."
        )
        wordcloud_response = requests.get(f"{BASE_URL}/wordcloud/{doc_id}/{song_title}")
        print(f"   -> Status Code: {wordcloud_response.status_code}")

        if wordcloud_response.status_code != 200:
            print("❌ Wordcloud 테스트 실패.")
            print(f"   -> 응답 내용: {wordcloud_response.text}")
        else:
            print("✅ Wordcloud 테스트 성공!")
            print(f"   -> GCS URL: {wordcloud_response.json().get('wordcloud_url')}")
        print("-" * 50)

    except requests.exceptions.ConnectionError:
        print("❌ 연결 실패: API 서버가 실행 중인지 확인하세요. (python api_server.py)")
    except Exception as e:
        print(f"❌ 예상치 못한 오류 발생: {e}")


if __name__ == "__main__":
    run_api_tests()
