import os
import time
import re
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import lyricsgenius
from firebase_admin import firestore
import concurrent.futures


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

        # Genius 설정
        genius_token = os.environ.get("GENIUS_TOKEN")
        if genius_token:
            # 기존 코드의 설정값 (timeout=15 등) 유지
            self.genius = lyricsgenius.Genius(genius_token, timeout=15)
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
        try:
            results = self.sp.playlist_items(playlist_id)
            tracks = results["items"]
            while results["next"]:
                results = self.sp.next(results)
                tracks.extend(results["items"])
        except Exception as e:
            print(f"Spotify Error: {e}")
            return None

        original_count = len(tracks)

        # 2. Genius 가사 병렬 수집
        processed_songs = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_song = {
                executor.submit(self._process_single_track, item): item
                for item in tracks
            }

            for future in concurrent.futures.as_completed(future_to_song):
                result = future.result()
                if result:
                    processed_songs.append(result)

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
        """트랙 하나를 처리하는 내부 로직 (기존 루프 내부 로직 이동)"""
        try:
            track = item["track"]
            if not track:
                return None

            title = track["name"]
            artist = track["artists"][0]["name"]

            # Genius 검색
            song = self.genius.search_song(title, artist)
            if not song:
                return None

            # 가사 전처리 (기존 _clean_lyrics 사용)
            clean_lyrics_text = self._clean_lyrics(song.lyrics)

            return {
                "original_title": title,
                "clean_title": title,
                "artist": artist,
                "lyrics": clean_lyrics_text,
                "album_art": (
                    track["album"]["images"][0]["url"]
                    if track["album"]["images"]
                    else None
                ),
            }
        except Exception as e:
            # 에러 시 None 리턴하여 스킵
            return None

    def _clean_lyrics(self, lyrics):
        """기존 get_lyrics_save_firestore.py의 정규식 로직 그대로 사용"""
        # [Verse 1] 등 태그 제거
        lyrics = re.sub(r"\[.*?\]", "", lyrics)
        # Contributors 제거
        lyrics = re.sub(r"^\d+ Contributors.*Lyrics", "", lyrics)
        return lyrics.strip()
