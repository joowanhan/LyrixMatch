import os
import re
import torch
from collections import Counter
from transformers import pipeline, AutoModelForSeq2SeqLM, AutoTokenizer
from konlpy.tag import Okt
from sklearn.feature_extraction.text import CountVectorizer
import deepl


class NLPService:
    def __init__(self):
        # 기존 환경변수 및 경로 설정
        self.deepl_key = os.environ.get("DEEPL_KEY")

        # [변경점] 경로 문제 해결: 실행 위치(project_root) 기준으로 경로 설정
        base_dir = os.getcwd()
        self.bart_path = os.path.join(base_dir, "models", "bart")
        self.t5_path = os.path.join(base_dir, "models", "eenzeenee_t5")

        # 모델 변수 초기화 (None)
        self.summarizer = None
        self.tokenizer = None
        self.model = None
        self.translator = None
        self.vectorizer = None
        self.okt = None

        # 초기화 시 바로 모델 로드 (Eager Loading 유지)
        self._load_models()

    def _load_models(self):
        """기존 load_all_models() 함수 로직"""
        print("⏳ [NLPService] AI 모델 로딩 중... (기존 설정 유지)")
        try:
            # 1. BART (영어 요약)
            # GPU 사용 가능 여부 확인 로직 유지
            device = 0 if torch.cuda.is_available() else -1
            self.summarizer = pipeline(
                "summarization", model=self.bart_path, device=device
            )

            # 2. T5 (한국어 요약)
            self.tokenizer = AutoTokenizer.from_pretrained(self.t5_path)
            self.model = AutoModelForSeq2SeqLM.from_pretrained(self.t5_path).to(
                torch.device("cuda" if torch.cuda.is_available() else "cpu")
            )

            # 3. DeepL
            if self.deepl_key:
                self.translator = deepl.Translator(self.deepl_key)

            # 4. 키워드 추출 도구
            self.vectorizer = CountVectorizer(stop_words="english")
            self.okt = Okt()

            print("✅ [NLPService] 모든 모델 로드 완료.")
        except Exception as e:
            print(f"❌ [NLPService] 모델 로딩 실패: {e}")

    def process_lyrics(self, lyrics, title=""):
        """기존 process_lyrics 함수 로직"""
        if not lyrics:
            return "가사 없음", []

        # 언어 감지 로직 유지
        kor_char_count = len(re.findall("[가-힣]", lyrics))
        total_char_count = len(lyrics)
        is_korean = (
            (kor_char_count / total_char_count) > 0.5 if total_char_count > 0 else False
        )

        summary_text = ""
        keywords = []

        try:
            if is_korean:
                summary_text = self._summarize_korean(lyrics)
                keywords = self._extract_keywords_korean(lyrics)
            else:
                summary_text = self._summarize_english(lyrics)
                keywords = self._extract_keywords_english(lyrics)
        except Exception as e:
            print(f"⚠️ 분석 중 오류 발생 ({title}): {e}")
            summary_text = "분석 실패"

        return summary_text, keywords

    def _summarize_english(self, text):
        # 기존의 길이 계산 로직 100% 유지
        input_len = len(text.split())
        max_len = min(100, max(30, int(input_len * 0.6)))
        min_len = max(10, int(input_len * 0.2))

        # BART 파이프라인 호출
        summary = self.summarizer(
            text[:4000], max_length=max_len, min_length=min_len, do_sample=False
        )
        full_summary = summary[0]["summary_text"]

        # 3문장 추출 로직 유지
        sentences = full_summary.split(". ")
        final_summary = ". ".join(sentences[:3]) + "."

        # DeepL 번역
        if self.translator:
            try:
                translated = self.translator.translate_text(
                    final_summary, target_lang="KO"
                )
                return translated.text
            except:
                pass
        return final_summary

    def _summarize_korean(self, text):
        # T5 생성 파라미터 유지 (max_length=128, num_beams=3)
        prefix = "summarize: " + text.replace("\n", " ")
        tokenized = self.tokenizer(prefix, return_tensors="pt").input_ids.to(
            self.model.device
        )
        output = self.model.generate(
            tokenized, max_length=128, num_beams=3, early_stopping=True
        )
        return self.tokenizer.decode(output[0], skip_special_tokens=True)

    def _extract_keywords_english(self, text):
        try:
            dtm = self.vectorizer.fit_transform([text])
            vocab = self.vectorizer.get_feature_names_out()
            dist = dtm.toarray().flatten()
            sorted_idx = dist.argsort()[::-1]
            return [vocab[i] for i in sorted_idx[:3]]
        except:
            return []

    def _extract_keywords_korean(self, text):
        try:
            nouns = self.okt.nouns(text)
            nouns = [n for n in nouns if len(n) > 1]
            count = Counter(nouns)
            return [word for word, _ in count.most_common(3)]
        except:
            return []
