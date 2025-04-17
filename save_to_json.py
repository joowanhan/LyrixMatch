import json
import re
import spacy

# 다국어 spaCy 모델 로드
nlp = spacy.load("xx_sent_ud_sm")

# JSON 파일 로드
with open('playlist_lyrics_clean.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 정규식 패턴
SECTION_RE = re.compile(r'\[.*?\]')  # [Intro], [Verse 1: ...] 등
READMORE_RE = re.compile(r'…\s*Read More.*?(?:\n|$)', flags=re.DOTALL)


def clean_lyrics(lyrics_raw) -> str:
    # lyrics_raw가 None이거나 문자열이 아니면 빈 문자열로 처리
    if not isinstance(lyrics_raw, str):
        lyrics_raw = ''

    # 1) 가사 시작 전 메타데이터 제거: 처음 '[' 이전 모든 텍스트 삭제
    idx = lyrics_raw.find('[')
    if idx != -1:
        text = lyrics_raw[idx:]
    else:
        text = lyrics_raw

    # 2) “… Read More […]” 블록 제거
    text = READMORE_RE.sub('', text)

    # 3) 섹션 태그 ([Intro], [Verse], [Chorus] 등) 제거
    text = SECTION_RE.sub('', text)

    # 4) 빈 줄, 과도한 공백 정리
    text = re.sub(r'\n{2,}', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)

    return text.strip()


# 전체 곡에 적용
for song in data:
    lyrics_raw = song.get('lyrics')  # 기본값 '' 안줘도 clean_lyrics 안에서 처리함
    lyrics_processed = clean_lyrics(lyrics_raw)
    song['lyrics_processed'] = lyrics_processed

# 결과 저장
with open('playlist_lyrics_processed.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"전처리된 가사가 'playlist_lyrics_processed.json'에 저장되었습니다.")
