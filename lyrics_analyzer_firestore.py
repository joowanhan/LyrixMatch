# lyrics_analyzer.py (Refactored for Eager Loading & Robustness)

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

# --- [Eager Loading] 1. 무거운 모듈을 최상단으로 이동 ---
import torch
from transformers import pipeline, AutoModelForSeq2SeqLM, AutoTokenizer
from konlpy.tag import Okt

# ---------------------------------------------------

# ────────────────────────────────
# --- 경고 메시지 숨기기 ---
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# ────────────────────────────────
# 환경 변수 / 토큰 설정
from dotenv import load_dotenv

load_dotenv()

DEEPL_KEY = os.environ.get("DEEPL_KEY")
BART_PATH = "./models/bart"
T5_PATH = "./models/eenzeenee_t5"

# ────────────────────────────────

# --- [Eager Loading] 2. 모델/객체를 None으로 전역 선언 ---
print("ℹ️ [Global Init] Declaring model variables as None.")
_summarizer_bart_pipeline = None
_tokenizer_t5 = None
_model_t5 = None
_translator_deepl = None
_vectorizer_en = None
_okt = None
# ────────────────────────────────


# --- [Eager Loading] 3. 모든 모델을 미리 로드하는 함수 신설 ---
def load_all_models():
    """서버 시작 시 호출될 함수. 모든 AI 모델과 토크나이저를 메모리에 로드."""
    global _summarizer_bart_pipeline, _tokenizer_t5, _model_t5
    global _translator_deepl, _vectorizer_en, _okt

    print("🔄 [Eager Load] Starting to load all models...")

    try:
        # 1. BART (영어 요약)
        if _summarizer_bart_pipeline is None:
            print("🔄 [Eager Load] Loading BART Model...")
            tokenizer = AutoTokenizer.from_pretrained(BART_PATH)
            model = AutoModelForSeq2SeqLM.from_pretrained(BART_PATH).to("cpu")
            _summarizer_bart_pipeline = pipeline(
                "summarization", model=model, tokenizer=tokenizer
            )
            print("✅ BART Model loaded.")

        # 2. T5 (한국어 요약)
        if _tokenizer_t5 is None or _model_t5 is None:
            print("🔄 [Eager Load] Loading T5 Model...")
            _tokenizer_t5 = AutoTokenizer.from_pretrained(T5_PATH)
            _model_t5 = AutoModelForSeq2SeqLM.from_pretrained(T5_PATH).to("cpu")
            print("✅ T5 Model loaded.")

        # 3. DeepL (번역)
        if _translator_deepl is None and DEEPL_KEY:
            print("🔄 [Eager Load] Loading DeepL Translator...")
            _translator_deepl = deepl.Translator(DEEPL_KEY)
            print("✅ DeepL Translator loaded.")
        elif not DEEPL_KEY:
            print("ℹ️ [Eager Load] DEEPL_KEY not set. Skipping DeepL.")

        # 4. CountVectorizer (영어 키워드)
        if _vectorizer_en is None:
            print("🔄 [Eager Load] Loading English Keyword Vectorizer...")
            _vectorizer_en = CountVectorizer(
                stop_words="english",
                token_pattern=r"(?u)\b[a-zA-Z]{3,}\b",
            )
            print("✅ English Keyword Vectorizer loaded.")

        # 5. Okt (한국어 키워드)
        if _okt is None:
            print("🔄 [Eager Load] Loading Korean (Okt) Tokenizer...")
            _okt = Okt()
            print("✅ Korean (Okt) Tokenizer loaded.")

        print("🎉 [Eager Load] All models loaded successfully.")

    except Exception as e:
        print(f"❌ [Eager Load] Critical error during model loading: {e}")
        # 로드 실패 시, 서버가 시작되지 않도록 예외를 다시 발생시킬 수 있음
        raise e


# ---------------------------  1) 언어 감지 --------------------------- #


def detect_language(text: str, hangul_weight: float = 0.5) -> str:
    """가사에서 한글·영문 문자 비율로 ‘ko’/‘en’ 반환."""
    hangul = re.findall(r"[가-힣]", text)
    latin = re.findall(r"[A-Za-z]", text)
    if len(hangul) + len(latin) == 0:
        return "en"
    return "ko" if len(hangul) / (len(hangul) + len(latin)) >= hangul_weight else "en"


# ---------------------------  2) 요약 --------------------------- #
# [수정] Lazy Loading 로직 제거. _summarizer_bart_pipeline이 이미 로드되었다고 가정.
def summarize_en(text: str, max_len: int = 90, min_len: int = 25) -> str:
    global _summarizer_bart_pipeline
    if _summarizer_bart_pipeline is None:
        raise Exception("BART model is not loaded.")  # Eager Loading 실패 시
    with torch.no_grad():
        summary = _summarizer_bart_pipeline(
            text, min_length=min_len, max_length=max_len, do_sample=False
        )[0]["summary_text"]
    return summary.strip()


# [수정] Lazy Loading 로직 제거. _tokenizer_t5와 _model_t5가 이미 로드되었다고 가정.
def summarize_ko(text: str, max_len: int = 64, min_len: int = 10) -> str:
    global _tokenizer_t5, _model_t5
    if _tokenizer_t5 is None or _model_t5 is None:
        raise Exception("T5 model is not loaded.")  # Eager Loading 실패 시

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
# [수정] Lazy Loading 로직 제거.
def translate_to_ko(text: str) -> str:
    global _translator_deepl
    if not _translator_deepl:
        # print("번역기 없음. 영어 요약 원본 반환.")
        return text
    return _translator_deepl.translate_text(text, target_lang="KO").text


# ---------------------------  4) 주요 단어 추출 --------------------------- #
# [수정] Lazy Loading 로직 제거.
def keywords_en(
    text: str, title: str, top_k: int = 10
) -> List[str]:  # [변경] title 인자 추가
    """영어 가사와 제목을 받아, 제목을 제외한 주요 단어 K개를 반환합니다."""
    global _vectorizer_en
    if _vectorizer_en is None:
        raise Exception("English Vectorizer is not loaded.")

    # [추가] 1. 제목에서 필터링할 단어(소문자) set 생성
    # CountVectorizer의 토큰 패턴과 유사하게 영어 단어만 추출
    title_words = set(re.findall(r"(?u)\b[a-zA-Z]+\b", title.lower()))

    X = _vectorizer_en.fit_transform([text.lower()])
    counts = X.toarray().sum(axis=0)
    vocab = _vectorizer_en.get_feature_names_out()
    freq = sorted(zip(vocab, counts), key=lambda x: x[1], reverse=True)

    # [추가] 2. freq 리스트에서 제목 단어 필터링
    # _vectorizer_en에 의해 vocab(w)은 이미 소문자, 3글자 이상, 불용어 제거됨
    filtered_freq = [(w, c) for w, c in freq if w not in title_words]

    # [변경] 필터링된 리스트(filtered_freq)에서 top_k 반환
    return [w for w, _ in filtered_freq[:top_k]]


# [수정] Lazy Loading 로직 제거.
def keywords_ko(
    text: str, title: str, top_k: int = 10
) -> List[str]:  # [변경] title 인자 추가
    """한국어 가사와 제목을 받아, 제목을 제외한 주요 단어 K개를 반환합니다."""
    global _okt
    if _okt is None:
        raise Exception("Korean (Okt) Tokenizer is not loaded.")

    # [추가] 1. 제목에서 필터링할 명사 set 생성 (2글자 이상)
    # 제목도 가사와 동일한 기준으로 명사 추출
    title_nouns = set([n for n in _okt.nouns(title) if len(n) > 1])

    # [변경] 2. 가사 명사 추출 시 제목 명사(title_nouns)에 없는 것만 필터링
    nouns = [n for n in _okt.nouns(text) if len(n) > 1 and n not in title_nouns]

    cnt = Counter(nouns).most_common(top_k)
    return [w for w, _ in cnt]


# ---------------------------  5) 전체 파이프라인 --------------------------- #


# [수정] 개별 곡 분석 실패 시 500 오류 대신 기본값을 반환하도록 try-except 추가
def process_lyrics(
    lyrics: str, title: str
) -> Tuple[str, List[str]]:  # [변경] title 인자 추가
    """
    가사와 제목을 받아 요약과 (제목이 필터링된) 키워드를 반환합니다.
    [Robustness] 모델 처리 중 오류 발생 시, 빈 문자열과 빈 리스트를 반환합니다.
    """
    try:
        lang = detect_language(lyrics)
        if lang == "en":
            # --- 영어 가사 처리 ---
            en_summary = summarize_en(lyrics)
            summary_ko = translate_to_ko(en_summary)
            # 영어 가사 -> 영어 제목(원본)으로 필터링
            kws = keywords_en(lyrics, title=title, top_k=10)
        else:
            # --- 한국어 가사 처리 ---
            summary_ko = summarize_ko(lyrics)
            # 'title' (예: "All For You")을 한국어로 번역 (예: "너를 위하여")
            # _translator_deepl이 None이면 원본(영어) title이 그대로 전달됨 (Robustness)
            translated_title_ko = translate_to_ko(title)

            # 한국어 가사 -> '번역된 한국어 제목'으로 필터링
            kws = keywords_ko(lyrics, title=translated_title_ko, top_k=10)

        return summary_ko, kws

    except Exception as e:
        # 개별 곡 분석 실패 시 (예: "index out of range in self")
        print(f"⚠️  [Analysis Error] Failed to process single lyric: {e}")
        # 서버 중단 대신, 이 곡에 대한 빈 결과를 반환
        return "", []


# ---------------------------  6) 실행 진입점 --------------------------- #
def main(doc_id: str, top_k: int = 10) -> None:
    """Firestore에서 Document ID로 가사 데이터를 가져와 분석합니다."""
    # --- [변경] Firebase 초기화를 main 함수 내부로 이동 ---
    import firebase_admin
    from firebase_admin import credentials, firestore

    try:
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
            print("✅ Firebase App initialized successfully (from module).")
    except Exception as e:
        print(f"❌ Firebase App initialization failed in module: {e}")

    db = firestore.client()
    # ---------------------------------------------------

    # --- [Eager Loading] 5. 로컬 실행 시에도 모델 로드 ---
    # (api_server.py가 아닌, 이 파일을 직접 실행할 경우)
    load_all_models()
    # -------------------------------------------------

    try:
        doc_ref = db.collection("user_playlists").document(doc_id)
        doc = doc_ref.get()

        if not doc.exists:
            raise FileNotFoundError(
                f"Firestore에서 Document ID '{doc_id}'를 찾을 수 없습니다."
            )

        data = doc.to_dict()
        songs = data.get("tracks", [])

        if not songs:
            print("해당 문서에 분석할 곡 데이터가 없습니다.")
            return

        for song in songs:
            title = song.get("clean_title") or song.get("original_title") or ""
            artist = song.get("artist", "Unknown")
            lyrics = song.get("lyrics_processed") or song.get("lyrics") or ""

            if not lyrics:
                print(f"\n[{title} - {artist}] 가사 정보가 없어 분석을 건너뜁니다.")
                continue

            # [변경] process_lyrics 호출 시 title 전달
            summary, kw = process_lyrics(lyrics, title=title)

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
