import spotipy
from spotipy.oauth2 import SpotifyOAuth
import lyricsgenius
import re
import json
from datetime import datetime

# Spotify API 설정
SPOTIFY_CLIENT_ID = '###########################'
SPOTIFY_CLIENT_SECRET = '###########################'
SPOTIFY_REDIRECT_URI = 'http://127.0.0.1:8888/callback'

# Genius API 설정
GENIUS_TOKEN = '###########################'
FAILED_SEARCH_LOG = 'failed_searches.log'  # 검색 실패 로그 파일


def clean_track_title(title):
    """트랙 제목에서 (with...) 및 (feat...) 제거"""
    return re.sub(r'\s*\(.*?\)', '', title).strip()


def expand_artists(original_artist, title):
    """피처링 아티스트 추출 및 확장"""
    featured = re.findall(r'\((?:with|feat\.?)\s([^)]+)\)', title)
    return original_artist + ' ' + ' '.join(featured) if featured else original_artist


def clean_genius_lyrics(raw_lyrics):
    """Genius 가사에서 Contributors/Translations 섹션 제거"""
    if not raw_lyrics:
        return None

    # Contributors 및 언어 목록 필터링
    cleaned_lines = []
    skip_line = False
    for line in raw_lyrics.split('\n'):
        if 'Contributors' in line or 'Translations' in line:
            skip_line = True
            continue
        if skip_line and re.match(r'^[\W\d_]*$', line):
            continue
        skip_line = False
        cleaned_lines.append(line.strip())

    # 마지막 Translations 텍스트 제거
    return '\n'.join(cleaned_lines).split('Translations')[0].strip()


def get_playlist_tracks(playlist_id):
    """Spotify 플레이리스트 트랙 정보 수집"""
    sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope='playlist-read-private',
        cache_path=".cache"
    ))

    try:
        results = sp.playlist_items(
            playlist_id, fields='items.track(name,artists(name))', limit=100)
        tracks = []
        while results:
            tracks.extend(results['items'])
            results = sp.next(results) if results.get('next') else None
        return [{
            'original_title': item['track']['name'],
            'clean_title': clean_track_title(item['track']['name']),
            'artist': item['track']['artists'][0]['name']
        } for item in tracks if item['track']]
    except Exception as e:
        print(f"Spotify API 오류: {str(e)}")
        return []


def get_lyrics(tracks):
    """Genius API를 통한 가사 검색 및 정제"""
    genius = lyricsgenius.Genius(GENIUS_TOKEN)
    lyrics_data = []

    for track in tracks:
        original_title = track['original_title']
        clean_title = track['clean_title']
        original_artist = track['artist']
        expanded_artist = expand_artists(original_artist, original_title)

        # 검색 쿼리 조합 (4가지 시나리오)
        search_attempts = [
            (clean_title, original_artist),    # 정제 제목 + 원본 아티스트
            (clean_title, expanded_artist),    # 정제 제목 + 확장 아티스트
            (original_title, original_artist),  # 원본 제목 + 원본 아티스트
            (original_title, expanded_artist)  # 원본 제목 + 확장 아티스트
        ]

        song = None
        for title, artist in search_attempts:
            try:
                song = genius.search_song(title, artist)
                if song:
                    break
            except Exception as e:
                print(f"검색 오류: {title} - {artist} | {str(e)}")

        if song:
            lyrics = clean_genius_lyrics(song.lyrics)
        else:
            lyrics = None
            # 검색 실패 로그 기록
            log_entry = f"{datetime.now()}|{original_artist}|{original_title}\n"
            with open(FAILED_SEARCH_LOG, 'a') as f:
                f.write(log_entry)

        lyrics_data.append({
            'original_title': original_title,
            'clean_title': clean_title,
            'artist': original_artist,
            'lyrics': lyrics
        })

    return lyrics_data


if __name__ == "__main__":
    playlist_id = '6UeSakyzhiEt4NB3UAd6NQ'

    # 데이터 수집
    print("🎵 Spotify 트랙 수집 중...")
    tracks = get_playlist_tracks(playlist_id)

    if tracks:
        print(f"✅ {len(tracks)}개 트랙 발견")

        print("🔍 Genius 가사 검색 시작...")
        lyrics = get_lyrics(tracks)

        # JSON 저장
        with open('playlist_lyrics_clean.json', 'w', encoding='utf-8') as f:
            json.dump(lyrics, f, indent=2, ensure_ascii=False)

        print(f"⚠️ 검색 실패 항목: {FAILED_SEARCH_LOG} 확인")
        print("🎉 최종 파일 저장 완료: playlist_lyrics_clean.json")
    else:
        print("❌ 트랙 수집 실패")