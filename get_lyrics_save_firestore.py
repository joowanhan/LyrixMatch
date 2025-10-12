#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_lyrics_save_firestore.py
───────────────────────
• Spotify 플레이리스트의 트랙 → Genius 가사 수집
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


def get_lyrics(tracks: list[dict]) -> list[dict]:
    """Genius API 여러 패턴으로 검색 → 가사 클린"""
    genius = lyricsgenius.Genius(
        GENIUS_TOKEN,
        timeout=15,
        retries=3,
        remove_section_headers=True,
    )
    out = []

    for t in tracks:
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
            try:
                song = genius.search_song(title, artist)
                if song:
                    break
            except Exception as e:
                print(f"[Genius 검색 오류] {title} – {artist} :: {e}")

        if song:
            lyrics = clean_genius_lyrics(song.lyrics)
        else:
            lyrics = None
            with open(FAILED_SEARCH_LOG, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now()}|{ori_artist}|{ori_title}\n")

        out.append(
            {
                "original_title": ori_title,
                "clean_title": clean_title,
                "artist": ori_artist,
                "lyrics": lyrics,
            }
        )
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
# deprecated
# get_lyrics_save_json.py의 구조를 함수화 (05/23 추가)
# firestore 저장으로 변경 후 deprecated


# def process_playlist_to_json(playlist_url: str) -> dict:
#     import re

#     playlist_id_match = re.search(r"playlist/([a-zA-Z0-9]+)", playlist_url)
#     if not playlist_id_match:
#         return {"error": "Invalid Spotify playlist URL"}

#     playlist_id = playlist_id_match.group(1)
#     main(playlist_id)
#     return {"message": "Lyrics saved successfully", "filename": OUTPUT_JSON}


# ────────────────────────────────
# 메인 실행
def main(playlist_id: str) -> str:
    """
    Spotify 플레이리스트 트랙과 가사 정보를 가져와 Firestore에 저장합니다.
    성공 시 생성된 문서의 ID를 반환합니다.
    """

    start = time.time()
    print("🎵 Spotify 트랙 수집 중…")
    tracks = get_playlist_tracks(playlist_id)

    if not tracks:
        print("❌ 트랙 수집 실패")
        return

    # Genius 가사 수집 + 1차 전처리 적용
    print(f"✅ {len(tracks)}개 트랙 발견 — Genius 가사 검색 시작")
    songs = get_lyrics(tracks)

    # 2차 전처리 적용
    print("💅 가사 전처리 진행중…")
    for s in songs:
        s["lyrics_processed"] = regex_clean_lyrics(s.get("lyrics"))

    # JSON 파일 저장 대신 Firestore에 데이터 저장
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
    # 테스트용 플레이리스트 ID
    test_playlist_url = "https://open.spotify.com/playlist/1KrcIM8VI1vYWe67dYWD3W"
    match = re.search(r"playlist/([a-zA-Z0-9]+)", test_playlist_url)
    if match:
        playlist_id = match.group(1)
        main(playlist_id)
