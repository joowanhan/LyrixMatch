"""
Using frequency: Using a dictionary of word frequency.
"""

# multidict는 동일한 키에 여러 값을 저장할 수 있는 딕셔너리 구조를 제공합니다.
import multidict as multidict

import numpy as np
import json
import os
import re
from PIL import Image
from os import path
from wordcloud import WordCloud, STOPWORDS, ImageColorGenerator
# ImageColorGenerator: 이미지 색상 추출
import matplotlib.pyplot as plt

# 운영체제에 따른 폰트 설정
import platform
system_name = platform.system()

if system_name == 'Windows':
    plt.rcParams['font.family'] = 'Malgun Gothic'  # 윈도우(맑은 고딕)
    font_path = 'C:\Windows\Fonts/malgun.ttf'  # 윈도우
    print('windows')
elif system_name == 'Darwin':  # Mac OS
    plt.rcParams['font.family'] = 'AppleGothic'  # 맥(애플고딕)
    font_path = '/Library/Fonts/AppleGothic.ttf'  # 맥
    print('mac')
else:  # Linux
    plt.rcParams['font.family'] = 'NanumGothic'  # Linux(나눔고딕)
    font_path = '/usr/share/fonts/truetype/malgun.ttf'  # 구글 콜랩
    print('linux')

plt.rcParams['axes.unicode_minus'] = False  # 마이너스 기호 깨짐 방지

# 단순한 코러스 불용어 추가
stopwords = set(STOPWORDS)
stopwords.add("uh")
stopwords.add("oh")
stopwords.add("huh")
stopwords.add("yeah")

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
        # max_words=50,
        # min_font_size=15,
        # max_font_size=150,
        stopwords=stopwords,
        mask=mask,
        color_func=image_colors
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
