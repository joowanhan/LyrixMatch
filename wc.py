"""
Using frequency: Using a dictionary of word frequency.
"""

# multidict는 동일한 키에 여러 값을 저장할 수 있는 딕셔너리 구조를 제공합니다.
import multidict as multidict

import string
import numpy as np
import json
import os
import re
from PIL import Image
from os import path
from wordcloud import WordCloud, STOPWORDS, ImageColorGenerator
# ImageColorGenerator: 이미지 색상 추출
import matplotlib.pyplot as plt

# Cloud Run은 컨테이너 안에 아무 폰트도 기본 포함되어 있지 않으니 로컬로 추가

font_path = "./fonts/NanumGothic.ttf"  # Cloud Run에서도 접근 가능한 경로


plt.rcParams['axes.unicode_minus'] = False  # 마이너스 기호 깨짐 방지

# 단순한 코러스 불용어 추가
stopwords = set(STOPWORDS)
stopwords.add("uh")
stopwords.add("eh")
stopwords.add("oh")
stopwords.add("ooh")
stopwords.add("ah")
stopwords.add("huh")
stopwords.add("yeah")
stopwords.add("la")
stopwords.add("woo")
stopwords.add("널")
stopwords.add("넌")
stopwords.add("좀")
stopwords.add("이")
stopwords.add("내")
stopwords.add("난")
stopwords.update(string.ascii_lowercase)

# 한국어 불용어 추가
# txt 파일에서 단어들을 읽어와서 set에 추가
with open("stopwords_kor.txt", "r", encoding="utf-8") as file:
    for line in file:
        word = line.strip()  # 줄 끝 개행 문자 제거
        if word:  # 빈 줄 방지
            stopwords.add(word)


# 단어 빈도 계산 함수


def getFrequencyDictForText(sentence: str, extra_stopwords: set[str] = None):
    extra_stopwords = extra_stopwords or set()
    all_stopwords = stopwords | extra_stopwords   # 전역+추가 합치기

    # 1) 문장부호 중 아포스트로피를 제외한 나머지를 공백으로 대체
    #    [^\w\s'] 는 영숫자(\w), 공백(\s), 그리고 ' 만 허용하겠다는 뜻입니다.
    sentence = re.sub(r"[^\w\s']", " ", sentence)

    # fullTermsDict: multidict.MultiDict() 구조로 변환하여 반환합니다.
    # 이는 동일한 키에 여러 값을 저장할 수 있습니다.
    fullTermsDict = multidict.MultiDict()
    # tmpDict: 단순히 단어와 그 빈도를 저장하는 임시 딕셔너리입니다.
    tmpDict = {}

    # 2) 공백 기준으로 분리
    for text in sentence.split():
        word = text.lower()
        # 3) 불용어 필터
        if word in all_stopwords or re.match(r"\b(a|an|the|to|in|for|of|or|by|with|is|on|that|be)\b", word):
            continue
        # 4) 소문자화 후 빈도 집계
        # tmpDict.get(text, 0): tmpDict 딕셔너리에서 현재까지 text의 빈도(key)를 반환합니다.
        # 소문자로 변환된 단어의 빈도를 계산하여 tmpDict에 저장합니다.
        tmpDict[word] = tmpDict.get(word, 0) + 1

    # 5) multidict에 추가
    fullTermsDict = multidict.MultiDict(tmpDict)
    return fullTermsDict


# 워드클라우드 생성 함수: 빈도 dict을 받아 내부에서 생성된 wc 객체를 반환


def makeWordCloud(freq_dict, title):
    mask = np.array(Image.open("mask_image.png"))
    mask_coloring = np.array(Image.open("mask_image.png"))
    # create coloring from image
    # 단어 클라우드의 각 단어가 배치된 위치에 따라, 이미지의 색상을 추출해 단어에 적용
    image_colors = ImageColorGenerator(mask_coloring)

    wc = WordCloud(
        background_color="white",
        font_path=font_path,
        max_words=50,
        # min_font_size=15,
        # max_font_size=300,
        stopwords=stopwords,
        mask=mask,
        color_func=image_colors,
        prefer_horizontal=1.0,  # 모든 단어를 수평으로
    )

    # generate word cloud
    wc.generate_from_frequencies(dict(freq_dict.items()))

    # show
    plt.figure(figsize=(10, 10))
    plt.title(title, fontsize=24)
    plt.imshow(wc, interpolation="bilinear")
    plt.axis("off")
    plt.show()


#########################################################################
# JSON 파일 불러오기
def generate_all_wordclouds(stopwords, getFrequencyDictForText, makeWordCloud):
    with open("playlist_lyrics_processed.json", "r", encoding="utf-8") as file:
        data = json.load(file)

# 객체별 워드클라우드 생성
    for item in data:
        # ── ① 곡 제목·아티스트 단어를 불용어에 추가 ───────────────────────────
        #    clean_title 이 있으면 특수문자·대소문자 처리가 끝난 상태이므로 그대로 써도 OK
        title_words = re.sub(r"[^\w\s']", " ", item["clean_title"]).split()
        artist_words = re.sub(
            r"[^\w\s']", " ", item["artist"]).split()  # 필요 없으면 제거
        title_stopwords = {w.lower() for w in title_words + artist_words}

    #    전역 stopwords 세트에 합친다 (루프마다 누적되지 않도록 copy 사용)
        local_stopwords = stopwords | title_stopwords

    # ── ② 가사 문자열 준비 ─────────────────────────────────────────────
    # lyrics_processed(문자열)를 합쳐 하나의 텍스트로
        lyrics = " ".join(item["lyrics_processed"].splitlines())

        try:
            print(title_stopwords)
        # ③ 단어 빈도 계산(추가 불용어 반영)
        # 가사 문자열을 넘겨줘야 split 에러가 안 납니다
            freq_dict = getFrequencyDictForText(
                lyrics,
                extra_stopwords=local_stopwords      # ← 수정: 함수 인자 추가
            )
        # ④ 워드클라우드 생성
            makeWordCloud(
                freq_dict, f"{item['original_title']} - {item['artist']}")

        except Exception as e:
            print(
                f"워드클라우드를 생성할 수 없습니다: {item['original_title']} - {item['artist']} ({e})")

#########################################################################


def generate_wordcloud_by_title(title_query: str) -> str:
    with open("playlist_lyrics_processed.json", "r", encoding="utf-8") as file:
        data = json.load(file)

    for item in data:
        title = item.get("clean_title", "").lower()
        if title == title_query.lower():
            title_words = re.sub(r"[^\w\s']", " ", item["clean_title"]).split()
            artist_words = re.sub(r"[^\w\s']", " ", item["artist"]).split()
            title_stopwords = {w.lower() for w in title_words + artist_words}
            local_stopwords = stopwords | title_stopwords
            lyrics = " ".join(item["lyrics_processed"].splitlines())

            freq_dict = getFrequencyDictForText(
                lyrics, extra_stopwords=local_stopwords)

            # 워드클라우드 이미지 저장
            mask = np.array(Image.open("mask_image.png"))
            image_colors = ImageColorGenerator(mask)
            wc = WordCloud(
                background_color="white",
                font_path=font_path,
                max_words=50,
                stopwords=stopwords,
                mask=mask,
                color_func=image_colors,
                prefer_horizontal=1.0,
            )
            wc.generate_from_frequencies(dict(freq_dict.items()))
            output_path = f"./static/wordclouds/{item['clean_title']}.png"
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            wc.to_file(output_path)
            return output_path

    raise ValueError("No matching song found")


# if __name__ == "__main__":
    # generate_all_wordclouds(stopwords, getFrequencyDictForText, makeWordCloud)
