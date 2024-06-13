from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import requests
import logging

app = FastAPI()

LAST_FM_API_KEY = '3165ed803092cb7d6e1087d1a389c45e'
LAST_FM_API_URL = 'http://ws.audioscrobbler.com/2.0/'

YOUTUBE_API_KEY = 'AIzaSyBoA4GTZUNWomcyC5WjMwCdV0V9GJjx0Wo'
YOUTUBE_API_URL = 'https://www.googleapis.com/youtube/v3/search'

templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")

logging.basicConfig(level=logging.INFO)

# 하드코딩된 링크 사전
HARDCODED_LINKS = {
    ('NewJeans', 'Hype Boy'): 'https://www.youtube.com/watch?v=MwIZz8zadqo'
}

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
async def artist_top_tracks(request: Request, artist_name: str):
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

    # YouTube 직캠 링크 추가
    for track in top_tracks:
        youtube_link = await get_youtube_fancam_link(track['name'], artist_name)
        track['youtube_link'] = youtube_link

    return templates.TemplateResponse("artist_toptracks.html", {
        "request": request,
        "artist_name": artist_name,
        "top_tracks": top_tracks
    })

async def get_youtube_fancam_link(track_name: str, artist_name: str):
    # 하드코딩된 링크 확인
    if (artist_name, track_name) in HARDCODED_LINKS:
        return HARDCODED_LINKS[(artist_name, track_name)]
    
    query = f"{track_name} {artist_name} 직캠"
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
    logging.info(f"YouTube API response: {response.json()}")
    
    if response.status_code != 200:
        logging.error(f"Failed to fetch YouTube video for {track_name} by {artist_name}: {response.status_code}")
        return None

    data = response.json()
    if 'items' in data and len(data['items']) > 0:
        video_id = data['items'][0]['id']['videoId']
        return f"https://www.youtube.com/watch?v={video_id}"
    logging.error(f"No YouTube video found for {track_name} by {artist_name}")
    return None
