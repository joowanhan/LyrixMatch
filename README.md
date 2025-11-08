# LyrixMatch

LyrixMatch는 자연어 처리(NLP) 기술을 활용하여 사용자가 노래 가사의 일부만 보고 원곡의 제목을 맞히는 Flutter 기반의 모바일 퀴즈 애플리케이션입니다. 사용자가 Spotify 플레이리스트 URL을 입력하면, 서버가 자동으로 가사를 수집 및 분석하여 요약문과 핵심 키워드를 추출하고, 이를 기반으로 퀴즈를 생성합니다.

---

## 🚀 주요 기능

* **Spotify 플레이리스트 연동**: 사용자는 자신의 Spotify 플레이리스트 URL을 입력하여 원하는 곡으로 퀴즈를 즐길 수 있습니다.
* **가사 분석 및 요약**: 최신 자연어 처리 모델(BART, T5 등)을 활용해 영어와 한국어 가사를 3문장 내외로 자동 요약하여 퀴즈 문제로 제공합니다.
* **핵심 키워드 추출**: NLTK, KoNLPy 라이브러리를 통해 가사에서 핵심 키워드 10개를 추출하여 힌트로 제공합니다.
* **워드클라우드 힌트**: 사용자가 추가 힌트를 원할 경우, 가사의 주요 단어로 구성된 워드클라우드 이미지를 실시간으로 생성하여 **Google Cloud Storage(GCS)에 업로드** 후, 고유 URL을 통해 시각적인 힌트를 안정적으로 제공합니다.
* **퀴즈 및 결과**: 사용자는 요약문과 키워드를 보고 노래 제목을 맞힐 수 있으며, 퀴즈 종료 후에는 맞힌 곡의 개수를 포함한 결과 페이지를 확인할 수 있습니다.

---

## ⚙️ 시스템 아키텍처

LyrixMatch는 **클라이언트-서버 구조**를 따릅니다.

* **클라이언트 (Flutter App)**: 사용자와의 상호작용을 담당하며, Spotify 플레이리스트 URL 입력, 퀴즈 풀이, 힌트 요청, 결과 확인 등의 기능을 수행합니다. 서버와는 REST API를 통해 통신합니다.
* **서버 (Flask API on Google Cloud Run)**: Python 기반의 Flask 프레임워크로 구현되었으며, Google Cloud Run을 통해 서버리스 환경에 배포됩니다. 가사 수집, 자연어 처리, 워드클라우드 생성 등 핵심 로직을 처리합니다. 특히, 다수의 곡을 처리할 때 발생하는 지연을 줄이기 위해 가사 수집 과정에 **병렬 처리를 도입**하여 성능을 최적화했습니다.
* **데이터베이스 (Firestore)**: 기존의 JSON 파일 저장 방식에서 Firestore로 업데이트하여, 가사 및 퀴즈 데이터를 보다 안정적으로 관리합니다.
* **스토리지 (Google Cloud Storage)**: 워드클라우드와 같이 생성된 이미지 파일들을 GCS에 영구 저장하여, 다중 사용자 환경에서도 데이터의 일관성과 안정성을 확보합니다.

---

## 🛠️ 기술 스택

### **서버 (Backend)**

* **언어**: Python 3.10
* **프레임워크**: Flask, waitress
* **배포**: Google Cloud Run, Docker
* **클라우드**: Firestore, Google Cloud Storage
* **주요 라이브러리**:
    * **API 연동**: Spotipy, LyricsGenius
    * **자연어 처리**: Hugging Face Transformers (BART, T5), NLTK, KoNLPy
    * **데이터 분석 및 시각화**: WordCloud, Matplotlib
    * **데이터베이스**: Firebase Admin

### **클라이언트 (Frontend)**

* **언어**: Dart 3.x
* **프레임워크**: Flutter 3.x
* **API 통신**: `http` 패키지

---

## 📖 API 엔드포인트

-   `POST /crawl`: Spotify 플레이리스트 URL을 받아 해당 곡들의 가사를 수집하고 분석하여 Firestore에 저장합니다.
-   `GET /quizdata`: Firestore에 저장된 퀴즈 데이터를 가져와 클라이언트에 전송합니다.
-   `GET /analyze/<doc_id>/<song_title>`: 특정 곡의 가사를 요약하고 키워드를 추출하여 반환합니다.
-   `GET /wordcloud/<doc_id>/<song_title>`: 특정 곡의 워드클라우드 이미지를 생성하여 GCS에 업로드하고 해당 URL을 반환합니다.
-   `GET /health`: 서버의 기본 상태를 확인합니다.
-   `GET /debug`: 서버의 상세 디버그 정보(메모리, Firestore 연결 상태 등)를 반환합니다.