import os
import io
from wordcloud import WordCloud, STOPWORDS
from google.cloud import storage
import matplotlib.pyplot as plt


class ImageService:
    def __init__(self, bucket_name="lyrixmatch-wordclouds"):
        self.bucket_name = bucket_name

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

        # GCS 클라이언트
        try:
            self.client = storage.Client()
            self.bucket = self.client.bucket(self.bucket_name)
        except Exception as e:
            print(f"Warning: GCS Client Error: {e}")
            self.client = None

        # --- 불용어 설정 (기존 wc.py 내용 그대로 적용) ---
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

    def generate_and_upload(self, text, title, artist):
        """워드클라우드 생성 및 업로드 로직"""
        if not text or not self.client:
            return None

        try:
            # 기존 파라미터 유지 (max_words=2000, width=800, height=800)
            wc = WordCloud(
                font_path=self.font_path,
                background_color="white",
                max_words=2000,
                stopwords=self.stopwords,
                width=800,
                height=800,
            )
            wc.generate(text)

            # 이미지를 파일로 저장하지 않고 메모리(BytesIO)에 저장
            img_data = io.BytesIO()
            wc.to_image().save(img_data, format="PNG")
            img_data.seek(0)

            # GCS 업로드
            filename = f"{artist}_{title}.png".replace(" ", "_")
            blob = self.bucket.blob(filename)
            blob.upload_from_file(img_data, content_type="image/png")

            return blob.public_url

        except Exception as e:
            print(f"WordCloud Error: {e}")
            return None
