#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_lyrics_save_firestore.py
───────────────────────
• Spotify 플레이리스트의 트랙 → Genius 가사 수집 (병렬 처리 적용)
• Contributors/Translations 블록 제거 + 정규식 기반 추가 전처리
• 최종 결과를 firestore에 저장 후 저장된 ID return
"""

import time
import json
import re
from datetime import datetime
import spotipy  # pip install spotipy

# from spotipy.oauth2 import SpotifyOAuth
from spotipy.oauth2 import SpotifyClientCredentials
import lyricsgenius  # pip install lyricsgenius

# ────────────────────────────────
# --- [변경] 병렬 처리를 위한 모듈 추가 ---
import concurrent.futures
from itertools import repeat

# ────────────────────────────────

# 환경 변수 / 토큰 설정
import os
from dotenv import load_dotenv  # --- 추가

# 로컬 개발 환경: .env 파일에서 환경 변수를 로드합니다.
load_dotenv()  # Cloud Run에는 .env 파일이 없으므로 이 라인은 무시됩니다.

# Cloud Run 호환: dotenv 대신 환경변수 직접 사용하는 코드로 변경
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI")
GENIUS_TOKEN = os.environ.get("GENIUS_TOKEN")

# ────────────────────────────────
# LOG 설정
FAILED_SEARCH_LOG = "failed_searches.log"  # 검색 실패 로그
# deprecated
# OUTPUT_JSON = "playlist_lyrics_processed.json"

# ────────────────────────────────
# 단일 json -> firestore 저장 위해 수정 (251002)
import uuid  # uuid 모듈 추가 - 각 요청에 대한 고유한 문서 ID를 생성

# Firebase Admin SDK 추가 및 초기화
import firebase_admin
from firebase_admin import firestore

# Firebase 앱 초기화
try:
    # 인수 없이 초기화
    # 1. 로컬: GOOGLE_APPLICATION_CREDENTIALS 환경 변수(.env)를 찾아 JSON 키로 인증
    # 2. Cloud Run: 환경 변수가 없으므로 ADC를 사용해 서비스 계정으로 자동 인증
    firebase_admin.initialize_app()
    print("✅ Firebase App initialized successfully using ADC.")
except Exception as e:
    print(f"❌ Firebase App initialization failed: {e}")
    # 이미 초기화된 경우를 대비한 예외 처리
    if not firebase_admin._apps:
        firebase_admin.initialize_app()

db = firestore.client()

# ────────────────────────────────
# Spotify 트랙 관련 유틸


def clean_track_title(title: str) -> str:
    """(with…)/(feat…)·'From …' 표기를 제거해 검색 최적화"""
    title = re.sub(r"\s*\(.*?\)", "", title)  # 괄호
    title = re.sub(r"\s*- From .*?$", "", title)  # - From
    title = re.sub(r"\s*\[From .*?\]", "", title)  # [From …]
    return title.strip()


def expand_artists(original_artist: str, title: str) -> str:
    """제목의 (feat./with …) 부분까지 아티스트에 포함"""
    featured = re.findall(r"\((?:with|feat\.?)\s([^)]+)\)", title)
    return f"{original_artist} {' '.join(featured)}" if featured else original_artist


def get_playlist_tracks(playlist_id: str) -> list[dict]:
    """Spotify 플레이리스트에서 트랙 제목·아티스트 추출"""
    sp = spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            # Cloud Run 환경에서는 SpotifyOAuth 대신 SpotifyClientCredentials 인증 방식이 안전하고 확실하게 작동합니다.
            # redirect_uri=SPOTIFY_REDIRECT_URI,
            # scope="playlist-read-private",
            # cache_path=".cache",
        )
    )

    results = sp.playlist_items(
        playlist_id,
        fields="items.track(name,artists(name))",
        limit=100,
    )

    # 모든 페이지를 순회하며 트랙 정보 수집
    tracks = []
    while results:
        # 현재 페이지의 트랙들을 tracks 리스트에 추가
        tracks.extend(results["items"])
        # 다음 페이지가 있으면 sp.next()로 다음 페이지 데이터를 가져오고, 없으면 None이 되어 루프 종료
        results = sp.next(results) if results.get("next") else None

    # 최종 수집된 트랙 정보 반환
    return [
        {
            "original_title": item["track"]["name"],
            "clean_title": clean_track_title(item["track"]["name"]),
            "artist": item["track"]["artists"][0]["name"],
        }
        for item in tracks
        if item.get("track")
    ]


# ────────────────────────────────
# Genius 가사 수집 + 1차 정제
def clean_genius_lyrics(raw_lyrics: str | None) -> str | None:
    """Genius 가사에서 Contributors·Translations 블록 제거"""
    if not raw_lyrics:
        return None

    cleaned_lines, skip = [], False
    for line in raw_lyrics.splitlines():
        if "Contributors" in line or "Translations" in line:
            skip = True
            continue
        if skip and re.match(r"^[\W\d_]*$", line):
            continue
        skip = False
        cleaned_lines.append(line.strip())

    return "\n".join(cleaned_lines).split("Translations")[0].strip()


# ────────────────────────────────
# --- [변경] 429 오류 대응을 위한 지수 백오프(Exponential Backoff) 로직 추가 ---
def fetch_single_lyric(t: dict, genius: lyricsgenius.Genius) -> dict:
    """트랙 1개에 대해 Genius API 검색 및 가사 추출 (스레드 작업용 + 429 재시도)"""

    # --- [신규] 재시도 로직을 위한 상수 ---
    MAX_RETRIES = 3  # 최대 재시도 횟수
    BASE_BACKOFF = 5  # 기본 대기 시간 (초). 5초, 10초, 20초로 증가.
    # ────────────────────────────────

    ori_title, clean_title = t["original_title"], t["clean_title"]
    ori_artist = t["artist"]
    exp_artist = expand_artists(ori_artist, ori_title)

    attempts = [
        (clean_title, ori_artist),
        (clean_title, exp_artist),
        (ori_title, ori_artist),
        (ori_title, exp_artist),
    ]

    song = None
    for title, artist in attempts:
        # --- [신규] 429 오류 대응을 위한 재시도 루프 ---
        for i in range(MAX_RETRIES):
            try:
                song = genius.search_song(title, artist)
                if song:
                    break  # --- [성공] 재시도 루프(inner loop) 탈출
            except Exception as e:
                # 429 오류 (Too Many Requests) 감지
                if "[Errno 429]" in str(e):
                    wait_time = BASE_BACKOFF * (2**i)  # 지수 백오프: 5s, 10s, 20s
                    print(
                        f"🚨 [Genius 429 Error] {title} – {artist}. {wait_time}초 후 재시도... (시도 {i+1}/{MAX_RETRIES})"
                    )
                    time.sleep(wait_time)
                else:
                    # 429가 아닌 다른 검색 오류 (e.g., 타임아웃, 500 서버 오류)
                    print(f"[Genius 검색 오류] {title} – {artist} :: {e}")
                    break  # 재시도 루프 탈출 (다음 attempt로 이동)

        if song:
            break  # --- [성공] 검색어 시도 루프(outer loop) 탈출

    if song:
        lyrics = clean_genius_lyrics(song.lyrics)
    else:
        lyrics = None
        # 스레드 환경에서 파일 쓰기. 'a'(append) 모드는 대부분 원자적(atomic)으로 동작하나,
        # 만약 로그가 꼬일 경우 python logging 모듈 사용 고려.
        try:
            with open(FAILED_SEARCH_LOG, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now()}|{ori_artist}|{ori_title}\n")
        except Exception as e:
            print(f"[Log 쓰기 오류] {ori_artist}|{ori_title} :: {e}")

    return {
        "original_title": ori_title,
        "clean_title": clean_title,
        "artist": ori_artist,
        "lyrics": lyrics,
    }


# --- [변경] get_lyrics 함수를 ThreadPoolExecutor를 사용하도록 수정 ---
def get_lyrics(tracks: list[dict]) -> list[dict]:
    """Genius API 여러 패턴으로 검색 → 가사 클린 (ThreadPoolExecutor 사용)"""
    genius = lyricsgenius.Genius(
        GENIUS_TOKEN,
        timeout=15,
        retries=3,  # 라이브러리 자체 재시도 (429 외의 오류에 도움됨)
        remove_section_headers=True,
    )

    # --- [변경] MAX_WORKERS를 10 -> 3으로 대폭 감소 (API Rate Limiting 대응) ---
    # IP 차단 해제 후 5 정도로 테스트하며 점진적 상향 고려
    MAX_WORKERS = 3
    out = []

    print(f"⚡️ {len(tracks)}개 트랙, {MAX_WORKERS}개 스레드로 동시 가사 수집 시작…")

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # executor.map을 사용하여 tracks의 각 항목을 fetch_single_lyric 함수에 동시 적용
        # repeat(genius)를 통해 모든 스레드에 동일한 genius 객체를 전달
        # list()로 감싸서 모든 스레드 작업이 완료되고 결과를 수집할 때까지 대기
        out = list(executor.map(fetch_single_lyric, tracks, repeat(genius)))

    return out


# ────────────────────────────────
# 2차 정규식 전처리 (save_to_json.py의 clean_lyrics)
# [Intro], [Verse 1: …] 등
SECTION_RE = re.compile(r"\[.*?\]")

READMORE_RE = re.compile(r".*Read More.*\n?", re.IGNORECASE)


def regex_clean_lyrics(lyrics_raw: str | None) -> str:
    """가사에서 섹션·메타데이터·과도한 공백 제거."""
    if not isinstance(lyrics_raw, str):
        lyrics_raw = ""

    # 1) 가사 시작 전 메타데이터 제거
    idx = lyrics_raw.find("[")
    text = lyrics_raw[idx:] if idx != -1 else lyrics_raw

    # 2) “Read More …” 블록 제거
    text = READMORE_RE.sub("", text)

    # 3) [Verse] 등 섹션 태그 제거
    text = SECTION_RE.sub("", text)

    # 4) 빈 줄·여분 공백 정리
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


# ────────────────────────────────
def process_playlist_and_save_to_firestore(playlist_url: str) -> str:
    """
    Spotify 플레이리스트 URL을 받아 ID를 추출하고,
    가사 수집 및 전처리 후 Firestore에 저장하고 문서 ID를 반환한다.
    """
    playlist_id_match = re.search(r"playlist/([a-zA-Z0_9]+)", playlist_url)
    if not playlist_id_match:
        raise ValueError("잘못된 Spotify 플레이리스트 URL입니다.")

    playlist_id = playlist_id_match.group(1)

    # main 함수를 호출하여 Firestore에 저장하고 문서 ID를 받는다.
    document_id = main(playlist_id)
    return document_id


# ────────────────────────────────
# 메인 실행
def main(playlist_id: str) -> str:
    """
    Spotify 플레이리스트 트랙과 가사 정보를 가져와 Firestore에 저장한다.
    성공 시 생성된 문서의 ID를 반환한다.
    """

    start = time.time()
    print("🎵 Spotify 트랙 수집 중…")
    tracks = get_playlist_tracks(playlist_id)

    if not tracks:
        print("❌ 트랙 수집 실패")
        return None  # 실패 시 None 반환 명시

    # Genius 가사 수집 + 1차 전처리 적용
    print(f"✅ {len(tracks)}개 트랙 발견 — Genius 가사 검색 시작")
    songs = get_lyrics(tracks)

    # 2차 전처리 적용
    print("💅 가사 전처리 진행중…")
    for s in songs:
        s["lyrics_processed"] = regex_clean_lyrics(s.get("lyrics"))

    # Firestore에 데이터 저장
    try:
        # 각 요청을 위한 고유 ID 생성
        request_id = str(uuid.uuid4())

        # 'user_playlists' 컬렉션에 request_id를 문서 이름으로 하여 데이터 저장
        doc_ref = db.collection("user_playlists").document(request_id)

        doc_ref.set(
            {
                "playlistId": playlist_id,
                "tracks": songs,
                "createdAt": firestore.SERVER_TIMESTAMP,  # 서버 시간 기준 생성 타임스탬프 기록
            }
        )

        print(
            f"---🎉 완료! Firestore에 데이터가 성공적으로 저장되었습니다. (Document ID: {request_id}) ---"
        )
        print(f"⏱ 실행 시간: {time.time() - start:.1f}s")
        return request_id

    except Exception as e:
        print(f"!!! Firestore 저장 중 오류 발생: {e}")
        return None


if __name__ == "__main__":
    # billboard hot 100
    # test_playlist_url = "https://open.spotify.com/playlist/6UeSakyzhiEt4NB3UAd6NQ"

    # 테스트용 플레이리스트 URL
    test_playlist_url = "https://open.spotify.com/playlist/0BLpwcj2ShVelGnbsmH7lW"
    # test_playlist_url = "https://open.spotify.com/playlist/1KrcIM8VI1vYWe67dYWD3W"

    match = re.search(r"playlist/([a-zA-Z0-9]+)", test_playlist_url)
    if match:
        playlist_id = match.group(1)
        main(playlist_id)
    else:
        # --- [추가] URL에서 ID를 찾지 못했을 경우 에러 메시지 ---
        print(
            f"❌ '{test_playlist_url}'에서 플레이리스트 ID를 추출할 수 없습니다. URL 형식을 확인하세요."
        )
