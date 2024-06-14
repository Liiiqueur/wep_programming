from fastapi import FastAPI, HTTPException, Request, Query, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, String, Integer, DateTime, func, desc
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import requests
import logging
import json
from datetime import datetime

# FastAPI 앱 초기화
app = FastAPI()

# Last.fm 및 YouTube API 키
LAST_FM_API_KEY = '3165ed803092cb7d6e1087d1a389c45e'
LAST_FM_API_URL = 'http://ws.audioscrobbler.com/2.0/'

YOUTUBE_API_KEY = 'AIzaSyDxxJnSmGz9bxgNRXAlVkZE7TMtri74lmU'  # YouTube API 키로 교체하세요
YOUTUBE_API_URL = 'https://www.googleapis.com/youtube/v3/search'

# Jinja2 템플릿 설정
templates = Jinja2Templates(directory="templates")

# 정적 파일 제공 설정
app.mount("/static", StaticFiles(directory="static"), name="static")

# 로깅 설정
logging.basicConfig(level=logging.INFO)

# 특정 트랙에 대한 하드코딩된 YouTube 링크
HARDCODED_LINKS = {
    ('NewJeans', 'Hype Boy'): 'https://www.youtube.com/watch?v=lmJPeFW75qQ',
    ('NewJeans', 'Attention'): 'https://www.youtube.com/watch?v=abcd1234',
    ('NewJeans', 'Ditto'): 'https://www.youtube.com/watch?v=abcd5678',
    ('김건모', '잘못된 만남'): 'https://www.youtube.com/watch?v=abcd9012'
}

# 캐시 파일 이름
CACHE_FILE = 'youtube_cache.json'

# 파일이 존재하면 캐시를 파일에서 로드
try:
    with open(CACHE_FILE, 'r') as f:
        cache = json.load(f)
except FileNotFoundError:
    cache = {}

# 셧다운 시 캐시를 파일에 저장
@app.on_event("shutdown")
def save_cache():
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f)

# 데이터베이스 URL 및 설정
DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 검색 기록을 위한 SQLAlchemy 모델
class SearchHistory(Base):
    __tablename__ = "search_history"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    artist_name = Column(String, index=True)
    track_name = Column(String, index=True, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

# 아티스트를 위한 SQLAlchemy 모델
class Artist(Base):
    __tablename__ = "artists"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    info = Column(String)
    similar_artists = Column(String)

# 트랙을 위한 SQLAlchemy 모델
class Track(Base):
    __tablename__ = "tracks"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    artist_name = Column(String, index=True)
    playcount = Column(Integer)
    release_date = Column(DateTime)
    youtube_link = Column(String)

# 데이터베이스에 모든 테이블 생성
Base.metadata.create_all(bind=engine)

# 데이터베이스 세션을 얻기 위한 종속성
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 최근 검색어를 표시하는 루트 엔드포인트
@app.get("/", response_class=HTMLResponse)
async def root(request: Request, db: Session = Depends(get_db)):
    recent_searches = db.query(SearchHistory).order_by(desc(SearchHistory.timestamp)).limit(10).all()

    return templates.TemplateResponse("index.html", {
        "request": request,
        "recent_searches": recent_searches
    })


# 아티스트 정보를 가져오는 엔드포인트
@app.get("/artist_info", response_class=HTMLResponse)
async def artist_info(request: Request, artist_name: str, db: Session = Depends(get_db)):
    # 검색 기록 저장
    search_record = SearchHistory(
        user_id=request.client.host,
        artist_name=artist_name,
        track_name=None
    )
    db.add(search_record)
    db.commit()

    # Last.fm API에서 아티스트 정보 가져오기
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

# 아티스트의 인기 트랙을 가져오는 엔드포인트
@app.get("/artist/{artist_name}/toptracks", response_class=HTMLResponse)
async def artist_top_tracks(request: Request, artist_name: str, sort_by: str = Query("popular"), db: Session = Depends(get_db)):
    # 검색 기록 저장
    search_record = SearchHistory(
        user_id=request.client.host,
        artist_name=artist_name,
        track_name=None
    )
    db.add(search_record)
    db.commit()

    # Last.fm API에서 인기 트랙 가져오기
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

    # 인기 순서 또는 발매일 순으로 트랙 정렬
    if sort_by == "latest":
        for track in top_tracks:
            track_info = get_track_info(artist_name, track['name'])
            track['release_date'] = track_info.get('release_date', '1900-01-01')
        sorted_tracks = sorted(top_tracks, key=lambda x: x['release_date'], reverse=True)
    else:
        sorted_tracks = sorted(top_tracks, key=lambda x: int(x['playcount']), reverse=True)

    # 상위 5개 트랙을 가져오고 YouTube 링크 가져오기
    top_5_tracks = sorted_tracks[:5]
    for track in top_5_tracks:
        youtube_link = await get_youtube_fancam_or_music_video_link(track['name'], artist_name)
        track['youtube_link'] = youtube_link

    other_tracks = [track for track in sorted_tracks if track not in top_5_tracks]

    return templates.TemplateResponse("artist_toptracks.html", {
        "request": request,
        "artist_name": artist_name,
        "top_tracks": top_5_tracks,
        "other_tracks": other_tracks
    })

# 트랙 정보를 가져오는 함수
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

# 트랙에 대한 YouTube 링크를 가져오는 함수
async def get_youtube_fancam_or_music_video_link(track_name: str, artist_name: str):
    cache_key = f"{artist_name}_{track_name}"
    if cache_key in cache:
        logging.info(f"Using cached link for {track_name} by {artist_name}")
        return cache[cache_key]

    if (artist_name, track_name) in HARDCODED_LINKS:
        logging.info(f"Using hardcoded link for {track_name} by {artist_name}")
        return HARDCODED_LINKS[(artist_name, track_name)]
    
    query = f"{track_name} {artist_name} 직캠"
    youtube_link = await search_youtube(query)
    if youtube_link:
        cache[cache_key] = youtube_link
        return youtube_link
    
    query = f"{track_name} {artist_name} 뮤직비디오"
    youtube_link = await search_youtube(query)
    if youtube_link:
        cache[cache_key] = youtube_link
        return youtube_link

    logging.error(f"No YouTube video found for {track_name} by {artist_name}")
    return None

# YouTube에서 비디오를 검색하는 함수
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

# 검색 기록에서 인기 아티스트를 가져오는 엔드포인트
@app.get("/analytics/popular_artists", response_class=JSONResponse)
async def popular_artists(request: Request, db: Session = Depends(get_db)):
    result = db.query(SearchHistory.artist_name, func.count(SearchHistory.artist_name).label("count")) \
               .group_by(SearchHistory.artist_name) \
               .order_by(func.count(SearchHistory.artist_name).desc()) \
               .limit(10) \
               .all()
    
    popular_artists = [{"artist_name": row[0], "count": row[1]} for row in result]
    return templates.TemplateResponse("popular_artists.html", {"request": request, "popular_artists": popular_artists})

# 검색 기록에서 인기 트랙을 가져오는 엔드포인트
@app.get("/analytics/popular_tracks", response_class=JSONResponse)
async def popular_tracks(request: Request, db: Session = Depends(get_db)):
    result = db.query(SearchHistory.track_name, func.count(SearchHistory.track_name).label("count")) \
               .group_by(SearchHistory.track_name) \
               .order_by(func.count(SearchHistory.track_name).desc()) \
               .limit(10) \
               .all()
    
    popular_tracks = [{"track_name": row[0], "count": row[1]} for row in result]
    return templates.TemplateResponse("popular_tracks.html", {"request": request, "popular_tracks": popular_tracks})

