import os
import random
import time
import re
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import lyricsgenius
from firebase_admin import firestore
import concurrent.futures
import requests


class MusicDataService:
    def __init__(self, db_client):
        self.db = db_client  # Firestore Client 주입

        # Spotify 설정
        client_id = os.environ.get("SPOTIFY_CLIENT_ID")
        client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")

        if client_id and client_secret:
            auth_manager = SpotifyClientCredentials(
                client_id=client_id, client_secret=client_secret
            )
            self.sp = spotipy.Spotify(auth_manager=auth_manager)
        else:
            self.sp = None
        PROXY_URL = ""
        # PROXY_URL = os.environ.get("PROXY_URL")
        proxies = None
        ip_used = "not_checked"  # IP 저장 변수
        if PROXY_URL:
            proxies = {"http": PROXY_URL, "https": PROXY_URL}
            print(f"✅ [Proxy] 프록시 설정을 사용합니다: {PROXY_URL.split('@')[-1]}")
            try:
                # 프록시를 통해 현재 IP 확인 (타임아웃 10초)
                r = requests.get(
                    "https://api.ipify.org?format=json", proxies=proxies, timeout=10
                )
                ip_used = r.json().get("ip", "proxy_ip_check_error")
                print(f"DEBUG: Proxy Outbound IP: {ip_used}")
            except Exception as e:
                print(f"DEBUG: Proxy IP Check Failed: {e}")
                ip_used = "proxy_ip_check_failed"
        else:
            print("ℹ️ [Proxy] 프록시 설정을 사용하지 않습니다 (직접 연결).")
            try:
                # 프록시 없이 현재 IP 확인 (타임아웃 5초)
                r = requests.get("https://api.ipify.org?format=json", timeout=5)
                ip_used = r.json().get("ip", "direct_ip_check_error")
                print(f"DEBUG: Direct Outbound IP: {ip_used}")
            except Exception as e:
                print(f"DEBUG: Direct IP Check Failed: {e}")
                ip_used = "direct_ip_check_failed"

            # user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
            # print(f"✅ user_agent 설정을 사용합니다: {user_agent}")

        # Genius 설정
        genius_token = os.environ.get("GENIUS_TOKEN")
        if genius_token:
            self.genius = lyricsgenius.Genius(
                genius_token,
                timeout=15,
                retries=3,  # 라이브러리 자체 재시도 (429 외의 오류에 도움됨)
                remove_section_headers=True,
                proxy=proxies,
                # user_agent=user_agent,
            )
            self.genius.verbose = False
        else:
            self.genius = None

    def fetch_and_save_playlist(self, playlist_id, request_id, client_ip):
        """기존 스크립트의 메인 로직을 메서드로 구현"""
        if not self.sp or not self.genius:
            print("API Clients not initialized")
            return None

        start_time = time.time()

        # 1. Spotify 트랙 가져오기
        print("🎵 Spotify 트랙 수집 중…")
        try:
            results = self.sp.playlist_items(playlist_id)
            tracks = results["items"]
            while results["next"]:
                results = self.sp.next(results)
                tracks.extend(results["items"])
        except Exception as e:
            print("❌ 트랙 수집 실패")
            print(f"Spotify Error: {e}")
            return None

        original_count = len(tracks)

        # 30곡 제한 설정
        # --- 플레이리스트 트랙 수 제한 로직 ---
        MAX_TRACKS_LIMIT = 30
        if original_count > MAX_TRACKS_LIMIT:
            print(
                f"✂️ {original_count}곡 발견 - {MAX_TRACKS_LIMIT}곡을 초과하여 무작위 {MAX_TRACKS_LIMIT}곡만 추출합니다."
            )
            tracks = random.sample(tracks, MAX_TRACKS_LIMIT)

        # 2. Genius 가사 병렬 수집
        print(f"✅ {len(tracks)}개 트랙 처리 시작 — Genius 가사 검색")
        MAX_WORKERS = 10
        processed_songs = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_song = {
                executor.submit(self._process_single_track, item): item
                for item in tracks
            }

            for future in concurrent.futures.as_completed(future_to_song):
                result = future.result()
                if result:
                    processed_songs.append(result)

        print("💅 가사 전처리 진행중…")

        # 3. Firestore 저장
        try:
            doc_ref = self.db.collection("user_playlists").document(request_id)
            doc_ref.set(
                {
                    "playlistId": playlist_id,
                    "tracks": processed_songs,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                    "originalTrackCount": original_count,
                    "processedTrackCount": len(processed_songs),
                    "requestIp": client_ip,
                }
            )
            print(
                f"Firestore Saved: {request_id} (Time: {time.time() - start_time:.1f}s)"
            )
            return request_id
        except Exception as e:
            print(f"Firestore Save Error: {e}")
            return None

    def _process_single_track(self, item):
        """
        트랙 하나를 처리 [통합 로직]
        1. Spotify Raw Data 파싱
        2. 재시도 및 다중 검색 전략
        3. 앨범 아트 포함 반환
        """
        try:
            track = item["track"]
            if not track:
                return None

            title = track["name"]
            title_clean = self._clean_title(title)
            artist = track["artists"][0]["name"]
            artist_expand = self._expand_artists(artist, title)

            # 검색 시도할 조합 목록 (우선순위 순서)
            search_attempts = [
                (title_clean, artist),  # 1순위: 정제된 제목 + 원본 가수
                (title_clean, artist_expand),  # 2순위: 정제된 제목 + 확장 가수
                (title, artist),  # 3순위: 원본 제목 + 원본 가수
                (title, artist_expand),  # 4순위: 원본 제목 + 확장 가수
            ]

            song = None
            MAX_RETRIES = 3
            BASE_BACKOFF = 5

            # Genius 검색
            # song = self.genius.search_song(title, artist)
            # 3. 검색 루프 (Outer Loop: 검색어 조합 변경)
            for title, artist in search_attempts:
                if not title or not artist:
                    continue

                # 4. 재시도 루프 (Inner Loop: 429 에러 대응)
                for i in range(MAX_RETRIES):
                    try:
                        song = self.genius.search_song(title, artist)
                        if song:
                            break  # 검색 성공 시 재시도 루프 탈출
                    except Exception as e:
                        error_msg = str(e)
                        # 429(Too Many Requests) 또는 403 에러 처리
                        if "429" in error_msg or "403" in error_msg:
                            error_code = 429 if "429" in error_msg else 403
                            wait_time = BASE_BACKOFF * (2**i)  # 5초 -> 10초 -> 20초
                            print(
                                f"🚨 [Genius {error_code} Error] {title} - {artist}. {wait_time}초 후 재시도... (시도 {i+1}/{MAX_RETRIES})"
                            )
                            time.sleep(wait_time)
                        else:
                            # 그 외 에러는 검색 실패로 간주하고 다음 검색어로 넘어감
                            print(
                                f"[Genius 검색/스크래핑 오류] {title} - {artist} :: {e}"
                            )
                            break

            if not song:
                return None

            # 가사 전처리
            clean_lyrics_text = self._clean_lyrics(song.lyrics)

            return {
                "original_title": title,
                "clean_title": title_clean,
                "artist": artist_expand,
                "lyrics": clean_lyrics_text,
                "album_art": (
                    track["album"]["images"][0]["url"]
                    if track["album"]["images"]
                    else None
                ),
            }
        except Exception as e:
            # 에러 시 None 리턴하여 스킵
            print(f"Skipping track. error: {e}")
            return None

    def _clean_lyrics(self, lyrics):
        """
        [통합 전처리 로직]
        1. Genius 메타데이터 헤더 제거 (강력한 정규식)
        2. 섹션 태그([Verse]) 제거
        3. 꼬리말(Embed, Read More) 제거
        4. 불필요한 공백 및 줄바꿈 정리
        """
        if not lyrics:
            return ""

        # 1. Genius 메타데이터 헤더 제거
        # 패턴: 맨 앞부터 "Lyrics"라는 단어가 나올 때까지의 모든 텍스트 삭제
        # (flags=re.DOTALL: 줄바꿈 포함해서 매칭)
        lyrics = re.sub(r"^.*?Lyrics", "", lyrics, flags=re.DOTALL | re.IGNORECASE)

        # 2. 섹션 태그 제거 ([Verse 1], [Chorus] 등)
        lyrics = re.sub(r"\[.*?\]", "", lyrics)

        # 3. 불필요한 꼬리말 제거
        # (숫자+Embed 로 끝나는 패턴 제거)
        lyrics = re.sub(r"\d*Embed$", "", lyrics)
        # (Read More 문구 제거)
        lyrics = re.sub(r".*Read More.*", "", lyrics, flags=re.IGNORECASE)

        # 4. Translations 이후 제거
        if "Translations" in lyrics:
            lyrics = lyrics.split("Translations")[0]

        # 5. 공백 정리
        # 여러 줄 바꿈 -> 한 줄 바꿈
        lyrics = re.sub(r"\n{2,}", "\n", lyrics)
        # 여러 공백 -> 한 공백
        lyrics = re.sub(r"[ \t]+", " ", lyrics)

        return lyrics.strip()

    def _clean_title(self, title: str) -> str:
        """(with…)/(feat…)·'From …' 표기를 제거해 검색 최적화"""
        title = re.sub(r"\s*\(.*?\)", "", title)  # 괄호
        title = re.sub(r"\s*- From .*?$", "", title)  # - From
        title = re.sub(r"\s*\[From .*?\]", "", title)  # [From …]
        return title.strip()

    def _expand_artists(self, original_artist: str, title: str) -> str:
        """제목의 (feat./with …) 부분까지 아티스트에 포함"""
        featured = re.findall(r"\((?:with|feat\.?)\s([^)]+)\)", title)
        return (
            f"{original_artist} {' '.join(featured)}" if featured else original_artist
        )
