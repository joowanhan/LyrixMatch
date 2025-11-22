import os
import io
import re
from dotenv import load_dotenv

from google.cloud import storage
import matplotlib.pyplot as plt
from PIL import Image

# multidict는 동일한 키에 여러 값을 저장할 수 있는 딕셔너리 구조를 제공합니다.
import multidict as multidict

# ImageColorGenerator: 이미지 색상 추출
import numpy as np
from wordcloud import WordCloud, STOPWORDS, ImageColorGenerator


# .env 파일 로드
load_dotenv()

# --- 기본 설정 ---
plt.rcParams["axes.unicode_minus"] = False  # 마이너스 기호 깨짐 방지


class ImageService:
    """
    ImageService 클래스
    -------------------
    가사(lyrics)로부터 워드클라우드를 생성하고 Google Cloud Storage(GCS)에 업로드하는 기능을 제공합니다.
    동일한 제목/아티스트 조합이 이미 업로드되어 있으면 캐시된 GCS 파일 경로를 반환합니다.
    마스크 이미지와 한글 폰트를 사용하여 커스텀된 워드클라우드를 생성합니다.
    """

    def __init__(self, bucket_name=os.getenv("GCS_BUCKET_NAME")):
        self.bucket_name = bucket_name

        # Cloud Run은 컨테이너 안에 아무 폰트도 기본 포함되어 있지 않으니 로컬로 추가
        # 경로 설정: app/static/fonts 등에서 파일을 찾도록 변경
        base_dir = os.getcwd()
        # 폰트 위치: app/static/fonts/NanumGothic.ttf
        self.font_path = os.path.join(
            base_dir, "app", "static", "fonts", "NanumGothic.ttf"
        )

        if not os.path.exists(self.font_path):
            print(f"❌ [CRITICAL] 폰트 파일을 찾을 수 없습니다: {self.font_path}")

        # 마스크 이미지 위치: app/static/mask_image.png (존재한다면)
        self.mask_path = os.path.join(base_dir, "app", "static", "mask_image.png")

        # 마스크 이미지를 Pillow로 열기
        self.mask_image_orginal = Image.open(self.mask_path)
        # 원하는 크기로 리사이징
        new_size = (800, 800)
        self.resized_mask_image = self.mask_image_orginal.resize(
            new_size, Image.Resampling.LANCZOS
        )  # LANCZOS는 고품질 리사이징 필터
        # 리사이징된 이미지를 numpy 배열로 변환하여 마스크로 사용
        self.mask = np.array(self.resized_mask_image)
        # 단어 클라우드의 각 단어가 배치된 위치에 따라, 이미지의 색상을 추출해 단어에 적용
        self.image_colors = ImageColorGenerator(self.mask)

        # GCS 클라이언트
        try:
            self.client = storage.Client()
            self.bucket = self.client.bucket(self.bucket_name)
        except Exception as e:
            print(f"Warning: GCS Client Error: {e}")
            self.client = None

        # --- 불용어 설정 ---
        self.stopwords = set(STOPWORDS)
        self.stopwords.update(
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

        # stopwords_kor.txt 파일이 있다면 로드 (경로 주의)
        stopwords_txt_path = os.path.join(
            base_dir, "app", "static", "stopwords_kor.txt"
        )
        if os.path.exists(stopwords_txt_path):
            try:
                with open(stopwords_txt_path, "r", encoding="utf-8") as f:
                    for line in f:
                        self.stopwords.add(line.strip())
            except:
                pass

    def _preprocess_lyrics(self, lyrics, title, artist) -> str:
        """워드클라우드 생성을 위한 텍스트 전처리"""
        # 곡 제목과 아티스트 이름을 추가 불용어로 설정
        title_words = {
            w.lower() for w in re.split(r"\s+", re.sub(r"[^\w\s']", "", title))
        }
        artist_words = {
            w.lower() for w in re.split(r"\s+", re.sub(r"[^\w\s']", "", artist))
        }

        # 정규식을 사용하여 불용어 처리
        all_stopwords = STOPWORDS | title_words | artist_words
        # \b는 단어 경계를 의미하여, a, is 같은 단어가 aple, island의 일부로 처리되는 것을 방지
        stopwords_pattern = (
            r"\b(" + "|".join(re.escape(word) for word in all_stopwords) + r")\b"
        )

        lyrics_processed = re.sub(stopwords_pattern, "", lyrics, flags=re.IGNORECASE)
        # 문장 부호 제거
        lyrics_processed = re.sub(r"[^\w\s']", " ", lyrics_processed)
        # 여러 공백을 하나로 축소
        lyrics_processed = re.sub(r"\s+", " ", lyrics_processed).strip()

        return lyrics_processed

    def _getFrequencyDict(self, lyrics):
        """가사 문자열을 통해 단어의 빈도 매핑 생성"""

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

    def generate_and_upload(self, lyrics, title, artist):
        """워드클라우드 생성 및 업로드 로직"""
        if not lyrics or not self.client:
            return None

        # 1. 캐시 키로 사용할 고유 파일 이름 생성 (소문자 + 특수문자는 _ 치환)
        # 원본 함수의 안전한 파일명 생성 로직 적용
        safe_title = "".join(c if c.isalnum() else "_" for c in title).lower()
        safe_artist = "".join(c if c.isalnum() else "_" for c in artist).lower()

        # 'wordclouds' 폴더 내부에 저장
        filename = f"wordclouds/{safe_title}_{safe_artist}.png"

        try:
            # 2. GCS 캐시 확인 (파일 존재 여부 체크)
            blob = self.bucket.blob(filename)

            if blob.exists():
                # [Cache Hit] 이미지가 이미 존재함
                print(f"✅ Cache Hit: GCS에서 '{filename}' 파일을 찾았습니다.")
                return blob.public_url

            # [Cache Miss] 이미지가 없으므로 생성 로직 진행
            print(f"❌ Cache Miss: '{filename}' 파일을 생성합니다.")

            # 3. 텍스트 전처리 (곡 제목, 아티스트 불용어 처리 포함)
            processed_lyrics = self._preprocess_lyrics(lyrics, title, artist)
            if not processed_lyrics:
                # 전처리 후 남은 텍스트가 없으면 빈 이미지 대신 오류나 기본 이미지 URL을 반환할 수 있다.
                raise ValueError(
                    "가사 텍스트가 너무 짧거나 불용어만으로 이루어져 있습니다."
                )

            freq_dict = self._getFrequencyDict(processed_lyrics)

            wc = WordCloud(
                font_path=self.font_path,
                background_color="white",
                mask=self.mask,  # 리사이징된 마스크를 사용
                max_words=50,
                color_func=self.image_colors,
                contour_width=1,
                contour_color="black",
                prefer_horizontal=1.0,  # 모든 단어를 수평으로
            ).generate_from_frequencies(dict(freq_dict.items()))

            # 이미지를 파일로 저장하지 않고 메모리(BytesIO)에 저장
            img_data = io.BytesIO()
            wc.to_image().save(img_data, format="PNG")
            img_data.seek(0)

            # GCS 업로드
            blob = self.bucket.blob(filename)
            blob.upload_from_file(img_data, content_type="image/png")

            return blob.public_url

        except Exception as e:
            print(f"워드클라우드 생성 또는 GCS 업로드 실패: {e}")
            return None
