from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import requests
import logging
import json
from datetime import datetime

app = FastAPI()

LAST_FM_API_KEY = '3165ed803092cb7d6e1087d1a389c45e'
LAST_FM_API_URL = 'http://ws.audioscrobbler.com/2.0/'

YOUTUBE_API_KEY = 'AIzaSyBoA4GTZUNWomcyC5WjMwCdV0V9GJjx0Wo'  # Replace with your YouTube API key
YOUTUBE_API_URL = 'https://www.googleapis.com/youtube/v3/search'

templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")

logging.basicConfig(level=logging.INFO)

# 하드코딩된 링크 사전
HARDCODED_LINKS = {
    ('NewJeans', 'Hype Boy'): 'https://www.youtube.com/watch?v=lmJPeFW75qQ',
    ('NewJeans', 'Attention'): 'https://www.youtube.com/watch?v=abcd1234',  # Replace with actual link
    ('NewJeans', 'Ditto'): 'https://www.youtube.com/watch?v=abcd5678',  # Replace with actual link
    # Add more hardcoded links here
    ('김건모', '잘못된 만남'): 'https://www.youtube.com/watch?v=abcd9012'  # Example link
}

# 캐시 파일 경로
CACHE_FILE = 'youtube_cache.json'

# 캐시 초기화
try:
    with open(CACHE_FILE, 'r') as f:
        cache = json.load(f)
except FileNotFoundError:
    cache = {}

@app.on_event("shutdown")
def save_cache():
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f)

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/artist_info", response_class=HTMLResponse)
async def artist_info(request: Request, artist_name: str):
    params = {
        'method': 'artist.getInfo',
        'artist': artist_name,
        'api_key': LAST_FM_API_KEY,
        'format': 'json'
    }
    response = requests.get(LAST_FM_API_URL, params=params)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="아티스트 정보를 가져오지 못했습니다")

    data = response.json()
    try:
        artist_data = data['artist']
        similar_artists = artist_data['similar']['artist'] if 'similar' in artist_data else []
    except KeyError as e:
        raise HTTPException(status_code=500, detail=f"예상치 못한 응답 구조: {str(e)}")

    return templates.TemplateResponse("artist_info.html", {
        "request": request,
        "artist_name": artist_name,
        "similar_artists": similar_artists
    })

@app.get("/artist/{artist_name}/toptracks", response_class=HTMLResponse)
async def artist_top_tracks(request: Request, artist_name: str, sort_by: str = Query("popular")):
    params = {
        'method': 'artist.getTopTracks',
        'artist': artist_name,
        'api_key': LAST_FM_API_KEY,
        'format': 'json'
    }
    response = requests.get(LAST_FM_API_URL, params=params)
    if response.status_code != 200:
        logging.error(f"Failed to fetch top tracks for {artist_name}: {response.status_code}")
        raise HTTPException(status_code=response.status_code, detail="인기 트랙 정보를 가져오지 못했습니다")

    data = response.json()
    top_tracks = []
    if 'toptracks' in data:
        top_tracks = data['toptracks']['track']
    else:
        logging.error(f"No top tracks found for {artist_name}")

    if sort_by == "latest":
        # 최신곡 순으로 정렬
        for track in top_tracks:
            track_info = get_track_info(artist_name, track['name'])
            track['release_date'] = track_info.get('release_date', '1900-01-01')
        sorted_tracks = sorted(top_tracks, key=lambda x: x['release_date'], reverse=True)
    else:
        # 인기 순으로 정렬 (기본값)
        sorted_tracks = sorted(top_tracks, key=lambda x: int(x['playcount']), reverse=True)

    # 상위 5개의 트랙에 대해서만 YouTube 링크를 추가
    top_5_tracks = sorted_tracks[:5]
    for track in top_5_tracks:
        youtube_link = await get_youtube_fancam_or_music_video_link(track['name'], artist_name)
        track['youtube_link'] = youtube_link

    # 나머지 트랙은 기본 정보만 포함
    other_tracks = [track for track in sorted_tracks if track not in top_5_tracks]

    # 트랙 정보 제공
    return templates.TemplateResponse("artist_toptracks.html", {
        "request": request,
        "artist_name": artist_name,
        "top_tracks": top_5_tracks,
        "other_tracks": other_tracks
    })

def get_track_info(artist_name: str, track_name: str):
    params = {
        'method': 'track.getInfo',
        'api_key': LAST_FM_API_KEY,
        'artist': artist_name,
        'track': track_name,
        'format': 'json'
    }
    response = requests.get(LAST_FM_API_URL, params=params)
    if response.status_code != 200:
        logging.error(f"Failed to fetch track info for {track_name} by {artist_name}: {response.status_code}")
        return {}

    data = response.json()
    track_info = {
        'release_date': data['track'].get('wiki', {}).get('published', '1900-01-01')
    }
    return track_info

async def get_youtube_fancam_or_music_video_link(track_name: str, artist_name: str):
    # 캐시 확인
    cache_key = f"{artist_name}_{track_name}"
    if cache_key in cache:
        logging.info(f"Using cached link for {track_name} by {artist_name}")
        return cache[cache_key]

    # 하드코딩된 링크 확인
    if (artist_name, track_name) in HARDCODED_LINKS:
        logging.info(f"Using hardcoded link for {track_name} by {artist_name}")
        return HARDCODED_LINKS[(artist_name, track_name)]
    
    # YouTube API를 통한 링크 검색
    query = f"{track_name} {artist_name} 직캠"
    youtube_link = await search_youtube(query)
    if youtube_link:
        cache[cache_key] = youtube_link
        return youtube_link
    
    # 직캠 검색에 실패하면 일반 검색어로 다시 검색
    query = f"{track_name} {artist_name} 뮤직비디오"
    youtube_link = await search_youtube(query)
    if youtube_link:
        cache[cache_key] = youtube_link
        return youtube_link

    # 두 번째 검색도 실패한 경우
    logging.error(f"No YouTube video found for {track_name} by {artist_name}")
    return None

async def search_youtube(query: str):
    params = {
        'part': 'snippet',
        'q': query,
        'key': YOUTUBE_API_KEY,
        'maxResults': 1,
        'type': 'video'
    }
    response = requests.get(YOUTUBE_API_URL, params=params)
    
    logging.info(f"Requesting YouTube API with query: {query}")
    logging.info(f"YouTube API response status: {response.status_code}")
    
    if response.status_code == 403:
        logging.error("YouTube API quota exceeded")
        return None

    data = response.json()
    logging.info(f"YouTube API response: {data}")
    
    if response.status_code != 200:
        logging.error(f"Failed to fetch YouTube video for query: {query}: {response.status_code}")
        return None

    if 'items' in data and len(data['items']) > 0:
        video_id = data['items'][0]['id']['videoId']
        return f"https://www.youtube.com/watch?v={video_id}"
    
    logging.error(f"No YouTube video found for query: {query}")
    return None
