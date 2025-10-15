# wc.py (Refactored - GCS ver.)

import os
import io
import re
import string
import numpy as np
from PIL import Image
from google.cloud import storage
from dotenv import load_dotenv
import matplotlib.pyplot as plt

# multidict는 동일한 키에 여러 값을 저장할 수 있는 딕셔너리 구조를 제공합니다.
import multidict as multidict

# ImageColorGenerator: 이미지 색상 추출
from wordcloud import WordCloud, STOPWORDS, ImageColorGenerator

# 로컬 개발 환경: .env 파일에서 환경 변수를 로드합니다.
# .env 파일 로드
load_dotenv()

# --- 기본 설정 ---
# Cloud Run은 컨테이너 안에 아무 폰트도 기본 포함되어 있지 않으니 로컬로 추가
FONT_PATH = "./fonts/NanumGothic.ttf"
plt.rcParams["axes.unicode_minus"] = False  # 마이너스 기호 깨짐 방지
MASK_IMAGE_PATH = "mask_image.png"

# --- 불용어 설정 ---
# 기본 불용어 + 한국어 불용어 파일을 한 번만 로드
STOPWORDS = set(STOPWORDS)
STOPWORDS.update(
    [
        "uh",
        "eh",
        "oh",
        "ooh",
        "ah",
        "huh",
        "yeah",
        "la",
        "woo",
        "널",
        "넌",
        "좀",
        "이",
        "내",
        "난",
    ]
)

# txt 파일에서 단어들을 읽어와서 set에 추가
with open("stopwords_kor.txt", "r", encoding="utf-8") as f:
    for line in f:
        STOPWORDS.add(line.strip())


def _preprocess_text_for_wordcloud(text: str, title: str, artist: str) -> str:
    """워드클라우드 생성을 위한 텍스트 전처리"""
    # 곡 제목과 아티스트 이름을 추가 불용어로 설정
    title_words = {w.lower() for w in re.split(r"\s+", re.sub(r"[^\w\s']", "", title))}
    artist_words = {
        w.lower() for w in re.split(r"\s+", re.sub(r"[^\w\s']", "", artist))
    }

    # 정규식을 사용하여 불용어 처리
    all_stopwords = STOPWORDS | title_words | artist_words
    # \b는 단어 경계를 의미하여, a, is 같은 단어가 aple, island의 일부로 처리되는 것을 방지
    stopwords_pattern = (
        r"\b(" + "|".join(re.escape(word) for word in all_stopwords) + r")\b"
    )

    processed_text = re.sub(stopwords_pattern, "", text, flags=re.IGNORECASE)
    # 문장 부호 제거
    processed_text = re.sub(r"[^\w\s']", " ", processed_text)
    # 여러 공백을 하나로 축소
    processed_text = re.sub(r"\s+", " ", processed_text).strip()

    return processed_text


def getFrequencyDict(lyrics):
    # 1) 문장부호 중 아포스트로피를 제외한 나머지를 공백으로 대체
    #    [^\w\s'] 는 영숫자(\w), 공백(\s), 그리고 ' 만 허용하겠다는 뜻입니다.
    lyrics = re.sub(r"[^\w\s']", " ", lyrics)

    # fullTermsDict: multidict.MultiDict() 구조로 변환하여 반환합니다.
    # 이는 동일한 키에 여러 값을 저장할 수 있습니다.
    fullTermsDict = multidict.MultiDict()
    # tmpDict: 단순히 단어와 그 빈도를 저장하는 임시 딕셔너리입니다.
    tmpDict = {}

    # 2) 공백 기준으로 분리
    for text in lyrics.split():
        # 3) 소문자화 후 빈도 집계
        word = text.lower()
        # tmpDict.get(text, 0): tmpDict 딕셔너리에서 현재까지 text의 빈도(key)를 반환합니다.
        # 소문자로 변환된 단어의 빈도를 계산하여 tmpDict에 저장합니다.
        tmpDict[word] = tmpDict.get(word, 0) + 1

    # 5) multidict에 추가
    fullTermsDict = multidict.MultiDict(tmpDict)
    return fullTermsDict


def generate_wordcloud_and_upload_to_gcs(
    lyrics: str, song_title: str, artist: str
) -> str:
    """
    가사를 받아 워드클라우드를 생성하고 GCS에 업로드 후, 공개 URL을 반환한다.
    """
    try:
        # 1. GCS 클라이언트 초기화
        gcs_credentials_path = os.getenv("GOOGLE_CLOUD_SERVICE_CREDENTIALS")
        if not gcs_credentials_path:
            raise ValueError(
                "GOOGLE_CLOUD_SERVICE_CREDENTIALS 환경변수가 설정되지 않았습니다."
            )

        storage_client = storage.Client.from_service_account_json(gcs_credentials_path)
        bucket_name = os.getenv("GCS_BUCKET_NAME")
        if not bucket_name:
            raise ValueError("GCS_BUCKET_NAME 환경변수가 설정되지 않았습니다.")
        bucket = storage_client.bucket(bucket_name)

        # 2. 캐시 키로 사용할 고유 파일 이름 생성 (소문자 + 안전한 문자)
        safe_title = "".join(c if c.isalnum() else "_" for c in song_title).lower()
        safe_artist = "".join(c if c.isalnum() else "_" for c in artist).lower()
        destination_blob_name = f"wordclouds/{safe_title}_{safe_artist}.png"

        # 3. GCS에 파일이 이미 존재하는지 확인 (캐시 확인)
        blob = bucket.blob(destination_blob_name)
        if blob.exists():
            print(f"✅ Cache Hit: GCS에서 '{destination_blob_name}' 파일을 찾았습니다.")
            return blob.public_url

        # --- 아래 로직은 파일이 존재하지 않을 때만 실행 (Cache Miss) ---
        print(f"❌ Cache Miss: '{destination_blob_name}' 파일을 생성합니다.")

        #############################################################################
        # 4. 텍스트 전처리 (곡 제목, 아티스트 불용어 처리 포함)
        processed_lyrics = _preprocess_text_for_wordcloud(lyrics, song_title, artist)
        if not processed_lyrics:
            # 전처리 후 남은 텍스트가 없으면 빈 이미지 대신 오류나 기본 이미지 URL을 반환할 수 있다.
            raise ValueError(
                "가사 텍스트가 너무 짧거나 불용어만으로 이루어져 있습니다."
            )

        # 5. 워드클라우드 생성
        # 마스크 이미지를 Pillow로 열기
        original_mask_image = Image.open(MASK_IMAGE_PATH)
        # 원하는 크기로 리사이징
        new_size = (800, 800)
        resized_mask_image = original_mask_image.resize(
            new_size, Image.Resampling.LANCZOS
        )  # LANCZOS는 고품질 리사이징 필터
        # 리사이징된 이미지를 numpy 배열로 변환하여 마스크로 사용
        mask = np.array(resized_mask_image)
        # 단어 클라우드의 각 단어가 배치된 위치에 따라, 이미지의 색상을 추출해 단어에 적용
        image_colors = ImageColorGenerator(mask)

        freq_dict = getFrequencyDict(processed_lyrics)

        wc = WordCloud(
            font_path=FONT_PATH,
            background_color="white",
            mask=mask,  # 리사이징된 마스크를 사용
            max_words=50,
            color_func=image_colors,
            contour_width=1,
            contour_color="black",
            prefer_horizontal=1.0,  # 모든 단어를 수평으로
        ).generate_from_frequencies(dict(freq_dict.items()))

        # 6. 이미지를 메모리 버퍼에 저장 및 업로드
        img_byte_arr = io.BytesIO()
        wc.to_image().save(img_byte_arr, format="PNG")
        img_byte_arr.seek(0)
        blob.upload_from_file(img_byte_arr, content_type="image/png")

        # 7. URL 반환
        # 객체 공개 및 URL 반환 - GCS 권한 수정으로 GCS 버킷이 모든 파일의 공개를 책임진다.
        return (
            blob.public_url
        )  # public_url 속성은 버킷이 공개 상태일 때 정상적으로 URL을 반환한다.

    except Exception as e:
        print(f"워드클라우드 생성 또는 GCS 업로드 실패: {e}")
        raise


#  로컬 테스트를 위한 실행 코드
# ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🚀 wc.py 로컬 테스트를 시작합니다...")

    # --- 테스트용 데이터 ---
    # 실제 가사처럼 보이도록 충분한 양의 텍스트를 준비한다.
    test_lyrics = """
    I'm on the next level yeah
    절대적 룰을 지켜
    내 손을 놓지 말아
    결속은 나의 무기
    광야로 걸어가
    알아 네 home ground
    위협에 맞서서
    제껴라 제껴라 제껴라
    상상도 못한 black out
    유혹은 깊고 진해
    (Too hot too hot)
    (Ooh ooh wee) 맞잡은 손을 놓쳐
    난 절대 포기 못해
    I'm on the next level
    저 너머의 문을 열어
    Next level
    널 결국엔 내가 부셔
    Next level
    Kosmo에 닿을 때까지
    Next level
    제껴라 제껴라 제껴라
    La la la la la la (ha, ha)
    La la la la la la
    La la la la la la
    La la la la la
    I see the NU EVO
    적대적인 고난과 슬픔은
    널 더 popping 진화시켜
    That's my Naevis
    It's my Naevis
    You lead, we follow
    감정들을 배운 다음
    Watch me while I make it out
    Watch me while I work it out
    Watch me while I make it out
    Watch me while I work it out
    Work it, work it, work it out
    감당할 수 없는 절망도
    내 믿음을 깨지 못해 (watch me while I work it)
    더 아픈 시련을 맞아도
    난 잡은 손을 놓지 않을게 (watch me while I work it) oh
    Beat drop
    Naevis, calling
    절대로 뒤를 돌아보지 말아
    광야의 것 탐내지 말아
    약속이 깨지면
    모두 걷잡을 수 없게 돼
    언제부턴가 불안해져 가는 신호
    널 파괴하고 말 거야 (we want it)
    Come on! Show me the way to Kosmo yeah yeah
    Black mamba가 만들어낸 환각 퀘스트
    Aespa, ae를 분리시켜놓길 원해 그래
    중심을 잃고 목소리도 잃고 비난받고
    사람들과 멀어지는 착각 속에
    Naevis 우리 ae, ae들을 불러봐
    Aespa의 next level "P.O.S"를 열어봐
    이건 real world 깨어났어
    We against the villain
    What's the name? Black mamba
    결국 난 문을 열어
    그 빛은 네겐 fire
    (Too hot too hot)
    (Ooh ooh wee)
    난 궁금해 미치겠어
    이 다음에 펼칠 story, huh!
    I'm on the next level
    저 너머의 문을 열어
    Next level
    널 결국엔 내가 부셔
    Next level
    Kosmo에 닿을 때까지
    Next level
    제껴라 제껴라 제껴라
    I'm on the next level
    더 강해져 자유롭게
    Next level
    난 광야의 내가 아냐
    Next level
    야수 같은 나를 느껴
    Next level
    제껴라 제껴라 제껴라 huh!
    """
    test_title = "Next Level"
    test_artist = "aespa"

    print(f"테스트 곡: {test_title} - {test_artist}")

    try:
        # 워드클라우드 생성 및 GCS 업로드 함수를 직접 호출한다.
        public_url = generate_wordcloud_and_upload_to_gcs(
            lyrics=test_lyrics, song_title=test_title, artist=test_artist
        )

        # --- 결과 확인 ---
        print("-" * 50)
        print("✅ 워드클라우드 생성 및 GCS 업로드 성공!")
        print(f"🔗 공개 URL: {public_url}")
        print("-" * 50)
        print(
            "위 URL을 복사하여 웹 브라우저에서 이미지가 올바르게 보이는지 확인하세요."
        )

    except Exception as e:
        print("-" * 50)
        print(f"❌ 테스트 중 오류가 발생했습니다.")
        print(f"오류 내용: {e}")
        print("-" * 50)
        print("💡 오류 해결을 위해 아래 사항을 확인하세요:")
        print(
            "1. .env 파일에 'GOOGLE_CLOUD_SERVICE_CREDENTIALS', 'GCS_BUCKET_NAME'이 정확히 설정되었는지 확인"
        )
        print("2. GCS 서비스 계정 키 파일 경로가 올바른지 확인")
        print(
            "3. GCS 버킷에 해당 서비스 계정이 'Storage 개체 관리자' 권한을 가지고 있는지 확인"
        )
        print("4. 인터넷 연결 상태 확인")
