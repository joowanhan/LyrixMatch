# LyrixMatch (Refact-OOP,gemini)

## **자연어 처리(NLP) 기반 가사-제목 추론형 퀴즈 서비스** 

LyrixMatch는 자연어 처리(NLP) 기술을 활용하여 사용자가 노래 가사의 일부만 보고 원곡의 제목을 맞히는 Flutter 기반의 모바일 퀴즈 애플리케이션입니다. 사용자가 Spotify 플레이리스트 URL을 입력하면, 서버가 자동으로 가사를 수집 및 분석하여 요약문과 핵심 키워드를 추출하고, 이를 기반으로 퀴즈를 생성합니다.

> *Legacy 코드를 OOP(객체 지향 프로그래밍) 및 MSC 아키텍처 도입, LLM 도입으로 리팩토링한 버전입니다.*

-----

## 🔄 Refactoring Highlights

기존의 절차지향적 스크립트 방식에서 발생하는 유지보수의 어려움과 테스트의 복잡성을 해결하기 위해 **대대적인 리팩토링**을 진행했습니다.

### 1\. MSC (Model-Service-Controller) 아키텍처 도입
MSC 패턴은 **Controller와 Model 사이에 Service Layer를 추가**하여 비즈니스 로직을 격리하는 아키텍처입니다.

| 계층 (Layer) | 구성 요소 (Component) | 역할 (Responsibility) | LyrixMatch 적용 예시 |
| :--- | :--- | :--- | :--- |
| **Controller** | `quiz_controller.py` | **"교통 정리"**<br>- HTTP 요청 수신 및 파라미터 검증<br>- 적절한 Service 호출<br>- 결과를 JSON으로 포맷팅하여 응답 | `/crawl` 요청을 받아 `playlist_id`가 있는지 확인하고 서비스에 넘김. |
| **Service** | `nlp_service.py`<br>`music_service.py`<br>`image_service.py` | **"실제 작업 수행"**<br>- 핵심 비즈니스 로직 구현<br>- 외부 API 연동, 계산, 데이터 가공<br>- DB 트랜잭션 관리 | Spotify에서 곡을 긁어오고, Genius 가사를 찾고, AI 요약을 수행함. |
| **Model** | (Firestore Dict) | **"데이터 구조"**<br>- 데이터베이스 스키마 정의<br>- 데이터 객체 (DTO) | Firestore의 `user_playlists` 컬렉션 구조. |

### 2\. 의존성 주입 (Dependency Injection)

  - 데이터베이스(Firestore)나 외부 API 클라이언트(Spotipy 등)를 클래스 내부에서 직접 생성하지 않고, 외부에서 주입받도록 변경했습니다.
  - 이를 통해 실제 DB 연결 없이도 비즈니스 로직을 검증할 수 있는 **테스트 가능한 구조**를 완성했습니다.

### 3\. 구조적 개선

  - **God Object 제거:** 모든 로직이 들어있던 `api_server.py`를 역할별로 분리했습니다.
  - **Lazy Analysis (지연 분석):** 모든 데이터를 한 번에 처리하지 않고, 사용자가 퀴즈를 요청하는 시점에 필요한 데이터만 분석하여 초기 로딩 속도를 획기적으로 개선했습니다.

또한 기존 로컬 LLM 운영 방식의 한계(느린 빌드, 높은 메모리 점유, 단일 언어 처리의 한계)를 극복하기 위해 **Google Gemini API**로 전면 교체했습니다.

### 4\. On-Premises to Cloud AI Migration (Server Lightweighting)
기존 로컬 LLM 운영 방식의 한계(느린 빌드, 높은 메모리 점유, 단일 언어 처리의 한계)를 극복하기 위해 **Google Gemini API**로 전면 교체했습니다.

1.  **AI 엔진 교체**: `BART(En)/T5(Ko)` → **`Gemini 2.5 Flash Lite`**
    * 로컬 메모리에 모델을 올리지 않아 **Cold Start 시간 0초** 달성.
    * 한영 혼용(K-POP) 가사의 문맥 이해도 및 요약 품질 대폭 향상.
2.  **구조화된 출력 (Structured Output)**: `Pydantic` 도입
    * AI 응답을 정규식으로 파싱하던 불안정한 로직 제거.
    * Type Safety가 보장된 객체(`AnalysisResult`)로 응답을 받아 데이터 정합성 확보.
3.  **빌드/배포 최적화**:
    * `PyTorch`, `Transformers`, `KoNLPy` 등 무거운 라이브러리 제거.
    * Docker 이미지 크기 **90% 이상 감소** (수 GB → 수백 MB).
    * **Git LFS 제거**로 CI/CD 파이프라인 속도 50% 이상 향상.

## 📂 프로젝트 구조 (Directory Structure)

리팩토링을 통해 역할별로 명확하게 분리된 디렉토리 구조를 갖추었습니다.

```bash
LyrixMatch-refact-OOP/
├── api_server.py           # 애플리케이션 진입점 (Entry Point)
├── app/
│   ├── __init__.py         # App Factory & DI 설정
│   ├── controllers/        # [Controller] API 라우팅 및 요청 처리
│   │   └── quiz_controller.py
│   ├── services/           # [Service] 핵심 비즈니스 로직
│   │   ├── music_service.py    # Spotify/Genius 연동 및 데이터 수집
│   │   ├── nlp_service.py      # AI 모델 로드 및 가사 요약/분석
│   │   └── image_service.py    # 워드클라우드 생성 및 GCS 업로드
│   └── static/             # 정적 리소스 (폰트, 불용어 리스트 등)
├── tests/                  # 단위 테스트 및 통합 테스트 (Pytest)
├── dockerfile              # 컨테이너 빌드 설정
└── requirements.txt        # 의존성 패키지 목록
```

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
  * 플러터 앱 소스코드: https://github.com/joowanhan/LyrixMatch-App
* **서버 (Flask API on Google Cloud Run)**: Python 기반의 Flask 프레임워크로 구현되었으며, Google Cloud Run을 통해 서버리스 환경에 배포됩니다. 가사 수집, 자연어 처리, 워드클라우드 생성 등 핵심 로직을 처리합니다. 특히, 다수의 곡을 처리할 때 발생하는 지연을 줄이기 위해 가사 수집 과정에 **병렬 처리를 도입**하여 성능을 최적화했습니다.
* **데이터베이스 (Firestore)**: 기존의 JSON 파일 저장 방식에서 Firestore로 업데이트하여, 가사 및 퀴즈 데이터를 보다 안정적으로 관리합니다.
* **스토리지 (Google Cloud Storage)**: 워드클라우드와 같이 생성된 이미지 파일들을 GCS에 영구 저장하여, 다중 사용자 환경에서도 데이터의 일관성과 안정성을 확보합니다.

-----

## 🛠️ 기술 스택 (Tech Stack)

### Backend (Server)

  * **Language:** Python 3.10
  * **Framework:** Flask (Blueprint 적용), Waitress
  * **Architecture:** MSC Pattern (Model-Service-Controller)
  * **AI & NLP:** **Google GenAI SDK (v2.0)**, **Pydantic**
  * **WordCloud**: WordCloud, Matplotlib
  * **Database:** Google Firestore (NoSQL)
  * **Storage:** Google Cloud Storage (GCS)
  * **Infra & Deploy:** Docker, Google Cloud Run, Cloud Build
  * **Testing:** Pytest, Unittest Mock

### Frontend (Client)

  * **Framework:** Flutter 3.x (Dart 3.x)
  * **Networking:** HTTP Package (REST API)

-----

## 📖 API 엔드포인트

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/crawl` | Spotify 플레이리스트 URL을 받아 곡 정보를 수집하고 DB에 저장 (병렬 처리) |
| **GET** | `/quizdata` | 저장된 퀴즈 데이터를 클라이언트로 전송 |
| **GET** | `/analyze/<doc_id>/<title>` | (지연 분석) 특정 곡의 요약문 및 키워드를 실시간 분석하여 반환 |
| **GET** | `/wordcloud/<doc_id>/<title>` | 워드클라우드 이미지를 생성하여 GCS 업로드 후 URL 반환 |
| **GET** | `/health` | 서버 상태 확인 (Health Check) |
<!-- | **GET** | `/debug` | 서버 리소스 및 DB 연결 상태 디버깅 정보 반환 | -->

-----

## 🔧 설치 및 실행 (Installation)

### 1\. 환경 설정

프로젝트 실행을 위해 `.env` 파일 또는 환경 변수 설정이 필요합니다 (Spotify API Key, Firebase Credential 등).

### 2\. 로컬 실행 (Docker)

```bash
# 이미지 빌드
docker build -t lyrixmatch-server .

# 컨테이너 실행
docker run -p 8080:8080 lyrixmatch-server
```

### 3\. 수동 실행 (Python)

```bash
# 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# 서버 실행
python api_server.py
```

-----

## 🧪 테스트 (Testing)

리팩토링된 코드의 안정성을 검증하기 위해 `pytest`를 사용합니다.

```bash
# 전체 테스트 실행
pytest

# 특정 테스트 실행
pytest tests/test_services.py
```

-----
