# lyrics_analyzer.py

#!/usr/bin/env python
# -*- coding: utf-8 -*-


import argparse
import json
import os
import re
from collections import Counter
from typing import List, Tuple
import nltk
import deepl
from sklearn.feature_extraction.text import CountVectorizer

# ────────────────────────────────
# --- 경고 메시지 숨기기 ---
# Hugging Face 토크나이저 병렬 처리 경고 비활성화
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# ────────────────────────────────
# 환경 변수 / 토큰 설정
from dotenv import load_dotenv  # --- 추가

# 로컬 개발 환경: .env 파일에서 환경 변수를 로드합니다.
load_dotenv()  # Cloud Run에는 .env 파일이 없으므로 이 라인은 무시됩니다.

# Cloud Run 호환: dotenv 대신 환경변수 직접 사용하는 코드로 변경
DEEPL_KEY = os.environ.get("DEEPL_KEY")
BART_PATH = "./models/bart"
T5_PATH = "./models/eenzeenee_t5"

# Cloud Run 컨테이너는 읽기 전용(read-only) 파일 시스템으로 실행되므로
# nltk.download("stopwords", quiet=True)
# nltk.download("punkt", quiet=True)
# ────────────────────────────────

# --- [변경] 모델/객체를 None으로 전역 선언 (Lazy Loading) ---
print("ℹ️ [Global Init] Declaring lazy-load model variables as None.")
_summarizer_bart_pipeline = None
_tokenizer_t5 = None
_model_t5 = None
_translator_deepl = None
_vectorizer_en = None
_okt = None
# ────────────────────────────────

# ---------------------------  1) 언어 감지 --------------------------- #


def detect_language(text: str, hangul_weight: float = 0.5) -> str:
    """가사에서 한글·영문 문자 비율로 ‘ko’/‘en’ 반환."""
    # 1. 한글 및 영문자 추출
    hangul = re.findall(r"[가-힣]", text)
    latin = re.findall(r"[A-Za-z]", text)

    # 2. 예외 처리: 한글/영문자가 모두 없는 경우
    if len(hangul) + len(latin) == 0:
        return "en"  # 기본값

    # 3. 언어 판별 로직
    return "ko" if len(hangul) / (len(hangul) + len(latin)) >= hangul_weight else "en"


# ---------------------------  2) 요약 --------------------------- #
# 영어 → BART summarizer


def summarize_en(text: str, max_len: int = 90, min_len: int = 25) -> str:
    global _summarizer_bart_pipeline  # 전역 변수 사용 선언
    # [추가] 라이브러리 임포트를 함수 내부로 이동
    import torch
    from transformers import pipeline, AutoModelForSeq2SeqLM, AutoTokenizer

    # [추가] 모델이 로드되지 않았으면 지금 로드
    if _summarizer_bart_pipeline is None:
        print("🔄 [Lazy Load] Loading BART Model...")
        tokenizer = AutoTokenizer.from_pretrained(BART_PATH)
        model = AutoModelForSeq2SeqLM.from_pretrained(BART_PATH).to("cpu")
        _summarizer_bart_pipeline = pipeline(
            "summarization", model=model, tokenizer=tokenizer
        )
        print("✅ BART Model loaded.")

    with torch.no_grad():
        summary = _summarizer_bart_pipeline(
            text, min_length=min_len, max_length=max_len, do_sample=False
        )[0]["summary_text"]
    return summary.strip()


# 한국어 →  t5-base-korean-summarization


def summarize_ko(text: str, max_len: int = 64, min_len: int = 10) -> str:
    global _tokenizer_t5, _model_t5  # 전역 변수 사용 선언

    # [추가] 라이브러리 임포트를 함수 내부로 이동
    import torch
    from transformers import pipeline, AutoModelForSeq2SeqLM, AutoTokenizer

    # [추가] 모델이 로드되지 않았으면 지금 로드
    if _tokenizer_t5 is None or _model_t5 is None:
        print("🔄 [Lazy Load] Loading T5 Model...")
        _tokenizer_t5 = AutoTokenizer.from_pretrained(T5_PATH)
        _model_t5 = AutoModelForSeq2SeqLM.from_pretrained(T5_PATH).to("cpu")
        print("✅ T5 Model loaded.")

    prefix = "summarize: "
    input_text = prefix + text.replace("\n", " ").strip()
    inputs = _tokenizer_t5(
        [input_text], max_length=512, truncation=True, return_tensors="pt"
    )

    with torch.no_grad():
        output = _model_t5.generate(
            **inputs,
            num_beams=3,
            do_sample=True,
            min_length=min_len,
            max_length=max_len,
            early_stopping=True,
        )
    decoded = _tokenizer_t5.batch_decode(output, skip_special_tokens=True)[0].strip()
    sentences = nltk.sent_tokenize(decoded)
    return " ".join(sentences[:3])


# ---------------------------  3) DeepL 번역 --------------------------- #


def translate_to_ko(text: str) -> str:
    global _translator_deepl

    # [추가] 번역기가 로드되지 않았으면 지금 로드
    if _translator_deepl is None and DEEPL_KEY:
        print("🔄 [Lazy Load] Loading DeepL Translator...")
        _translator_deepl = deepl.Translator(DEEPL_KEY)
        print("✅ DeepL Translator loaded.")

    if not _translator_deepl:
        print("번역기 없음. 영어 요약 원본 반환.")
        return text  # DeepL 키가 없으면 영어 원본 반환
    return _translator_deepl.translate_text(text, target_lang="KO").text


# ---------------------------  4) 주요 단어 추출 --------------------------- #


def keywords_en(text: str, top_k: int = 10) -> List[str]:

    global _vectorizer_en

    # [추가] 벡터라이저가 로드되지 않았으면 지금 로드
    if _vectorizer_en is None:
        print("🔄 [Lazy Load] Loading English Keyword Vectorizer...")
        _vectorizer_en = CountVectorizer(
            stop_words="english",
            token_pattern=r"(?u)\b[a-zA-Z]{3,}\b",  # 3자 이상 알파벳
        )
        print("✅ English Keyword Vectorizer loaded.")

    X = _vectorizer_en.fit_transform([text.lower()])
    counts = X.toarray().sum(axis=0)
    vocab = _vectorizer_en.get_feature_names_out()
    freq = sorted(zip(vocab, counts), key=lambda x: x[1], reverse=True)
    return [w for w, _ in freq[:top_k]]


def keywords_ko(text: str, top_k: int = 10) -> List[str]:

    global _okt
    # [추가] 라이브러리 임포트를 함수 내부로 이동
    from konlpy.tag import Okt

    # [추가] Okt가 로드되지 않았으면 지금 로드
    if _okt is None:
        print("🔄 [Lazy Load] Loading Korean (Okt) Tokenizer...")
        _okt = Okt()
        print("✅ Korean (Okt) Tokenizer loaded.")

    nouns = [n for n in _okt.nouns(text) if len(n) > 1]  # 2글자 이상
    cnt = Counter(nouns).most_common(top_k)
    return [w for w, _ in cnt]


# ---------------------------  5) 전체 파이프라인 --------------------------- #


def process_lyrics(lyrics: str) -> Tuple[str, List[str]]:
    lang = detect_language(lyrics)
    if lang == "en":
        en_summary = summarize_en(lyrics)
        summary_ko = translate_to_ko(en_summary)
        kws = keywords_en(lyrics)
    else:
        summary_ko = summarize_ko(lyrics)
        kws = keywords_ko(lyrics)
    return summary_ko, kws


# ---------------------------  6) 실행 진입점 --------------------------- #
def main(doc_id: str, top_k: int = 10) -> None:
    """Firestore에서 Document ID로 가사 데이터를 가져와 분석합니다."""
    # --- [변경] Firebase 초기화를 main 함수 내부로 이동 ---
    import firebase_admin
    from firebase_admin import credentials, firestore

    try:
        if not firebase_admin._apps:
            cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred)
            print("✅ (Main) Firebase App initialized successfully.")
    except Exception as e:
        print(f"❌ (Main) Firebase App initialization failed: {e}")
    db = firestore.client()
    # ---------------------------------------------------

    try:
        doc_ref = db.collection("user_playlists").document(doc_id)
        doc = doc_ref.get()

        if not doc.exists:
            raise FileNotFoundError(
                f"Firestore에서 Document ID '{doc_id}'를 찾을 수 없습니다."
            )

        data = doc.to_dict()
        songs = data.get(
            "tracks", []
        )  # get_lyrics_save_firestore.py에서 'tracks' 필드에 저장

        if not songs:
            print("해당 문서에 분석할 곡 데이터가 없습니다.")
            return

        for song in songs:
            title = song.get("clean_title") or song.get("original_title")
            artist = song.get("artist", "Unknown")
            lyrics = song.get("lyrics_processed") or song.get("lyrics") or ""

            if not lyrics:
                print(f"\n[{title} - {artist}] 가사 정보가 없어 분석을 건너뜁니다.")
                continue

            summary, kw = process_lyrics(lyrics)

            # ----- 결과 출력 ----- #
            print(f"\n[{title} - {artist}]")
            print(f"요약 (3문장): {summary}")
            print(f"주요 단어 {top_k}개: {', '.join(kw)}")

    except Exception as e:
        print(f"데이터 처리 중 오류 발생: {e}")


# 로컬 실행 방법
# python lyrics_analyzer.py <your-firestore-document-id>
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Firestore에서 가사 데이터를 가져와 분석합니다."
    )
    parser.add_argument("doc_id", type=str, help="Firestore의 Document ID")
    parser.add_argument("--top_k", type=int, default=10, help="추출할 주요 단어의 수")
    args = parser.parse_args()

    main(doc_id=args.doc_id, top_k=args.top_k)

# python lyrics_analyzer_firestore.py 85e90cd7-319e-4f00-87de-f4bebd4518ac
