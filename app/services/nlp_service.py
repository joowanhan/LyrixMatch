import os
from google import genai
from google.genai import types
from pydantic import BaseModel, Field


# 1. 응답 데이터 구조 정의 (Pydantic)
# Gemini가 이 스키마에 맞춰서 정확한 JSON을 생성하도록 강제합니다.
class AnalysisResult(BaseModel):
    summary: str = Field(
        description="가사의 핵심 서사와 감정을 요약한 텍스트. 3문장 이내의 한국어 하십시오체(예: 노래합니다)를 사용."
    )
    keywords: list[str] = Field(
        description="가사에서 가장 핵심적인 단어 10개 리스트. 제목에 포함된 단어와 불용어는 제외. 중요: 키워드는 번역하지 말고 반드시 가사의 원문 언어(영어 가사면 영어, 한국어 가사면 한국어) 그대로 추출할 것."
    )


class NLPService:
    def __init__(self):
        # 2. 클라이언트 초기화
        # 환경변수 GEMINI_API_KEY 자동으로 감지합니다.
        self.api_key = os.environ.get("GEMINI_API_KEY")

        if not self.api_key:
            print("⚠️ [NLPService] 경고: GEMINI_API_KEY가 설정되지 않았습니다.")
            self.client = None
        else:
            # v2.0 SDK는 인스턴스화 시 키를 명시하지 않아도 환경변수를 읽지만,
            # 명시적으로 넣어주는 것이 안전합니다.
            self.client = genai.Client(api_key=self.api_key)
            print("✅ [NLPService] Google GenAI SDK Client (v2.0) 초기화 완료.")

    def process_lyrics(self, lyrics, title=""):
        """
        Gemini 2.5 Flash Lite를 사용하여 가사 요약 및 키워드 추출
        """
        # 방어 코드
        if not lyrics:
            return "가사 없음", []
        if not self.client:
            return "API 키 미설정 오류", []

        # 3. 프롬프트 구성
        prompt = f"""
        당신은 통찰력 있는 음악 퀴즈 출제자입니다. 
        아래 노래 정보를 분석하여 구조화된 데이터를 추출해주세요.

        [곡 정보]
        - 제목: {title}
        - 가사:
        {lyrics}
        """

        try:
            # 4. API 호출 (구조화된 출력 사용)
            response = self.client.models.generate_content(
                model="gemini-2.5-flash-lite",  # 최신 경량 모델 사용
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=AnalysisResult,  # Pydantic 클래스 직접 전달
                    temperature=0.3,
                    # 안전 설정: 가사의 예술적 표현 허용 (BLOCK_NONE 적용)
                    safety_settings=[
                        types.SafetySetting(
                            category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"
                        ),
                        types.SafetySetting(
                            category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"
                        ),
                        types.SafetySetting(
                            category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                            threshold="BLOCK_NONE",
                        ),
                        types.SafetySetting(
                            category="HARM_CATEGORY_DANGEROUS_CONTENT",
                            threshold="BLOCK_NONE",
                        ),
                    ],
                ),
            )

            # 5. 결과 반환 (SDK가 Pydantic 객체로 자동 변환해줌)
            if response.parsed:
                return response.parsed.summary, response.parsed.keywords
            else:
                # 파싱된 결과가 없는 경우 (매우 드묾)
                print(f"⚠️ [NLPService] 파싱된 응답 없음. 원문: {response.text}")
                return "분석 실패", []

        except Exception as e:
            print(f"❌ [NLPService] Gemini 분석 실패: {e}")
            return "AI 서비스 오류 발생", []
