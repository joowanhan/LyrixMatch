# api_server.py
from spotipy.oauth2 import SpotifyOAuth
import spotipy
from flask import request, redirect
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import json
import os
from lyrics_analyzer import process_lyrics
from get_lyrics_save_json import process_playlist_to_json
from wc import generate_wordcloud_by_title


app = Flask(__name__)
CORS(app)  # Flutter에서 요청할 수 있게 허용


# ────────────────────────────────

# api_server.py에 추가 (05/23)
@app.route("/crawl", methods=["POST"])
def crawl_playlist():
    try:
        data = request.get_json()

        # 디버깅용으로 추가함
        print("Headers:", request.headers)
        print("Raw data:", request.data)
        print("Parsed JSON:", data)

        if data is None:
            return jsonify({"error": "Invalid JSON or missing headers"}), 400

        playlist_url = data.get("playlist_url", "")

        if not playlist_url:
            return jsonify({"error": "Missing playlist_url"}), 400

        result = process_playlist_to_json(playlist_url)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ────────────────────────────────


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json()
        lyrics = data.get("lyrics", "")

        if not lyrics:
            return jsonify({"error": "Missing lyrics"}), 400

        summary, keywords = process_lyrics(lyrics)
        return jsonify({
            "summary": summary,
            "keywords": keywords
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ────────────────────────────────


@app.route("/quizdata", methods=["GET"])
def quizdata():
    try:

        json_path = "playlist_lyrics_processed.json"
        if not os.path.exists(json_path):
            return jsonify({"error": "No playlist data found. Run /crawl first."}), 400

        with open(json_path, encoding="utf-8") as f:
            raw = json.load(f)

        result = []
        for song in raw:
            lyrics = song.get("lyrics_processed", "") or ""
            if not lyrics.strip():
                continue
            summary, keywords = process_lyrics(lyrics)
            result.append({
                "title": song["clean_title"],
                "summary": summary,
                "keywords": keywords
            })

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ────────────────────────────────
# wc endpoint 추가 (05/29)


@app.route("/wordcloud", methods=["GET"])
def wordcloud():
    try:
        title = request.args.get("title", "")
        if not title:
            return jsonify({"error": "Missing title"}), 400

        # 워드클라우드 생성 및 파일 저장
        image_path = generate_wordcloud_by_title(title)

        return jsonify({"image_path": image_path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/static/wordclouds/<filename>")
def serve_image(filename):
    return send_from_directory("static/wordclouds", filename)

# ────────────────────────────────
# Spotify OAuth 인증 후 리디렉션 받을 엔드포인트 추가 (06/05)


@app.route("/callback")
def spotify_callback():
    sp_oauth = SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
        scope="user-library-read"
    )
    session_code = request.args.get("code")
    if session_code:
        token_info = sp_oauth.get_access_token(session_code)
        return {"access_token": token_info['access_token']}
    else:
        return "Authorization failed", 400
# ────────────────────────────────


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
