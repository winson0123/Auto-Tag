# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import asyncio
import re
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, POPM
from tqdm import tqdm
from google import genai
from pyrekordbox import Rekordbox6Database
from pyrekordbox.db6 import tables
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# -------------------- CONFIG --------------------
MUSIC_DIR = os.getenv("MUSIC_DIR", r"C:\Path\To\Your\Music\Library")  # Set via .env file or change this path
BITRATE_MIN = 320_000
ENERGY_MAP_PATH = "energy_map.json"
PROCESSED_SONGS_PATH = "processed_songs.json"
GENAI_API_KEY = os.getenv("GENAI_API_KEY", "")  # Get your free API key from https://aistudio.google.com/apikey

# SoundCloud API (optional - for accurate genre tagging from SoundCloud)
# To get these: Go to soundcloud.com logged in, open Dev Tools (F12), Network tab, refresh
# Look for requests to find: client_id (32 char alphanumeric) and Authorization header (OAuth token)
SOUNDCLOUD_CLIENT_ID = os.getenv("SOUNDCLOUD_CLIENT_ID", "")  # Leave empty to disable SoundCloud lookup
SOUNDCLOUD_AUTH_TOKEN = os.getenv("SOUNDCLOUD_AUTH_TOKEN", "")  # Format: "OAuth 2-XXXXXX-XXXXXXXX-XXXXXXXXXXX"

# API Rate Limiting (Gemini free tier: 10 requests per minute)
API_DELAY_SECONDS = 7  # Delay between requests (7 seconds = ~8.5 requests/minute, safe margin)
MAX_RETRIES = 5  # Number of retries for rate limit errors
RETRY_BASE_DELAY = 60  # Base delay for exponential backoff on 429 errors


# Initialize new Google GenAI client (latest SDK)
client = genai.Client(api_key=GENAI_API_KEY)

# SoundCloud client will be initialized per-request with async session
soundcloud_enabled = bool(SOUNDCLOUD_CLIENT_ID and SOUNDCLOUD_AUTH_TOKEN)
if soundcloud_enabled:
    try:
        from soundcloudpy import SoundcloudAsyncAPI
        import aiohttp
    except ImportError:
        soundcloud_enabled = False

PROMPT_INSTRUCTIONS = """You are a music metadata assistant for DJ music libraries. CRITICAL: Identify the genre based on the REMIXER'S/PRODUCER'S typical style and how they tag their own releases, not just the original song's genre.

IMPORTANT ARTIST/PRODUCER GENRE KNOWLEDGE:
- For remixes, the genre often differs from the original - a pop song remix by an Afro House producer becomes Afro House
- Check remixer's discography and typical production style
- If you recognize the remixer's name, use their signature genre

SEARCH PRIORITY (check in this order):
1. Remixer's typical genre/style - If you know the remixer (e.g., Ale Lucchi does Afro House), use that genre
2. Track characteristics - Percussion patterns, basslines, vocal style
3. Platform tags - How this type of remix is typically categorized on Beatport/Traxsource
4. DJ community consensus - How DJs in that genre scene would classify it

GENRE GUIDELINES - READ CAREFULLY:
⛔ FORBIDDEN VAGUE GENRES - NEVER USE THESE:
- "EDM" (too vague - specify: Big Room, Electro House, Progressive House, Festival House, etc.)
- "Dance" (too vague - specify: Dance-Pop, House, Tech House, etc.)
- "Electronic" (too vague - specify the actual subgenre)
- "Club" or "Club Music" (too vague - unless it's specifically a "Club Mix" which becomes a subgenre tag)
- NEVER use artist names, remixer names, or producer names as genres (e.g., "Barbangerz", "Zedd", "Tiësto" are NOT genres)

✅ HOW TO BE SPECIFIC:
- Instead of "EDM" → use "Big Room", "Electro House", "Progressive House", "Festival House", "Mainstage"
- Instead of "Dance" → use "Dance-Pop", "House", "Tech House", "Electro House"
- Instead of "Electronic" → use "Techno", "House", "Trance", "Dubstep", etc.
- NEVER use the artist/remixer name as a genre - always use the actual music genre/style
- Listen for key characteristics:
  * Four-on-the-floor kick + percussive groove = "Tech House" or "Afro House"
  * Four-on-the-floor + melodic synths + build-ups = "Progressive House" or "Electro House"
  * Heavy bass drops + wobbles = "Dubstep" or "Bass House"
  * Fast-paced + breakbeats = "Drum & Bass" or "Jungle"
  * Synthesized beats + rap vocals = "Hip-Hop" or "Trap"

After each song prompt, only respond strictly in this format:
Is Remix: <ONLY respond with "Yes" or "No". "Yes" if the title contains remix/edit/bootleg/flip/VIP/rework/refix indicators OR remixer names in parentheses. "No" if it's the original version>
Genre: <use PRECISE DJ/music pool genre names. For REMIXES: use the REMIXER'S genre style. For ORIGINALS: use the original song's genre. BE SPECIFIC - avoid vague umbrella terms! Common genres: "Tech House", "Afro House", "Afro", "Progressive House", "Electro House", "Future Bass", "Bass House", "French House", "Trap", "Hip-Hop", "R&B", "Pop", "K-Pop", "Dance-Pop", "Dubstep", "Drum & Bass", "House", "Deep House", "Techno", "Trance", "Hardstyle", "UK Garage", "Jersey Club", "Jersey", "Afrobeats", "Reggae", "Reggaeton", "Moombahton", "Big Room", "Mainstage", "Festival House", "Funky House", "Disco House", "Nu Disco", "Tropical House", "Speed House", "Ghetto House", "Circuit House", "Club House", "Melbourne Bounce", "Psytrance", "Acid House", "Breakbeat", "Breaks", "Organic House", "Melodic House", "Country", "Disco", "Funk", etc. If multiple genres apply, use "/" to separate them like "Afro House / Melodic House">
Original Artists: <main artist and any featured artists, comma delimited>
Original Song Release: <year of release of the ORIGINAL song, not the remix>
Situation: <ONLY respond with "Bar", "Club", or "Both" - nothing else. Use "Bar" for laid-back/moderate energy tracks, "Club" for high-energy dance tracks, "Both" if it works in either setting>
Commercial Friendly: <ONLY respond with "Yes" or "No". "Yes" if the song has clean lyrics (no explicit content, profanity, or controversial themes) and is appropriate for commercial venues like restaurants, retail stores, corporate events, or radio. "No" if it contains explicit content, profanity, or adult themes>
"""

# -------------------- UTILITIES --------------------
def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_bitrate(file_path):
    try:
        audio = MP3(file_path)
        return audio.info.bitrate
    except Exception:
        return 0

def get_artist_from_file(file_path):
    """Extract artist from MP3 file metadata only (no fallback to filename)."""
    try:
        audio = EasyID3(file_path)
        artist = audio.get('artist', [''])[0]
        return artist if artist else None
    except Exception:
        return None

def extract_remixer_from_title(title):
    """Extract remixer name from title like 'Song (Remixer Name Remix)'."""
    # Pattern: anything in parentheses before keywords like Remix, Edit, Bootleg, etc.
    # Example: "Song (Ale Lucchi Remix)" -> "Ale Lucchi"
    patterns = [
        r'\(([^)]+?)\s+(?:Remix|Edit|Bootleg|Flip|VIP|Rework|Refix|Mix)\)',  # (Name Remix)
        r'\[([^\]]+?)\s+(?:Remix|Edit|Bootleg|Flip|VIP|Rework|Refix|Mix)\]',  # [Name Remix]
    ]
    
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            remixer = match.group(1).strip()
            # Clean up common prefixes
            remixer = re.sub(r'^(?:DJ\s+|dj\s+)', '', remixer)
            return remixer if remixer else None
    
    return None

def extract_genre_from_remix_title(title, energy_map):
    """
    Extract genre from remix title if genre name is included.
    Example: "Song (Esquire Afro House Remix)" -> "Afro House"
    Only extracts multi-word genres to avoid false matches with artist names.
    Uses genres from energy_map.json for consistency.
    """
    # Collect all genres from energy map
    known_genres = []
    for level, genre_list in energy_map.items():
        known_genres.extend(genre_list)
    
    # Filter to only multi-word genres (2+ words) to avoid false matches
    # Single words like "groove", "house", "funk" are too common in artist names
    multi_word_genres = [g for g in known_genres if ' ' in g or '&' in g or '-' in g]
    
    # Extract only the remix/edit portion (what's in parentheses/brackets before Remix/Edit/etc.)
    # Example: "Song (Groove Coverage Afro House Remix)" -> extract "groove coverage afro house"
    remix_patterns = [
        r'\(([^)]+?)\s+(?:Remix|Edit|Bootleg|Flip|VIP|Rework|Refix|Mix)\)',  # (Name Remix)
        r'\[([^\]]+?)\s+(?:Remix|Edit|Bootleg|Flip|VIP|Rework|Refix|Mix)\]',  # [Name Remix]
    ]
    
    for pattern in remix_patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            remix_content = match.group(1).lower()
            
            # Look for multi-word genre names (prioritize longer/more specific names first)
            # e.g., "afro house", "tech house", "drum & bass", "dance-pop"
            for genre in sorted(multi_word_genres, key=len, reverse=True):
                # Check if genre appears as a distinct phrase (word boundaries)
                genre_pattern = r'\b' + re.escape(genre) + r'\b'
                if re.search(genre_pattern, remix_content):
                    # Convert to Title Case using normalize_genre_case
                    return normalize_genre_case(genre)
    
    return None

def detect_transition(title):
    """
    Detect if a track is a transition track based on BPM pattern in title.
    Example: "Song (Transition 128-94)" or "Song 128-94" -> True
    Returns True if transition pattern found, False otherwise.
    """
    # Pattern: two numbers separated by a dash (BPM transition)
    # Example: "128-94", "130-100", etc.
    transition_pattern = r'\b(\d{2,3})-(\d{2,3})\b'
    
    match = re.search(transition_pattern, title)
    if match:
        # Verify these look like BPM values (typically 60-200)
        bpm1 = int(match.group(1))
        bpm2 = int(match.group(2))
        if 60 <= bpm1 <= 200 and 60 <= bpm2 <= 200:
            return True
    
    return False

def detect_club_mix(title):
    """
    Detect if a track is a club mix based on title patterns.
    Example: "Song (Club Mix)", "Song (Club Version)", "Song - Club Mix" -> True
    Returns True if club mix pattern found, False otherwise.
    """
    # Pattern: look for "club mix", "club version", "club edit", etc.
    club_patterns = [
        r'\bclub\s+mix\b',
        r'\bclub\s+version\b',
        r'\bclub\s+edit\b',
        r'\bclub\s+remix\b',
    ]
    
    title_lower = title.lower()
    for pattern in club_patterns:
        if re.search(pattern, title_lower):
            return True
    
    return False

def normalize_genre_case(genre):
    """
    Normalize genre to Title Case for consistency.
    Handles multi-genre strings with slashes.
    Example: "tech house / house" -> "Tech House / House"
    """
    if not genre:
        return genre
    
    # Split by "/" for multi-genre
    genres = [g.strip() for g in genre.split('/')]
    
    # Title case each genre, handling special cases
    normalized = []
    for g in genres:
        # Special handling for acronyms and special terms
        if g.upper() in ['EDM', 'DNB', 'R&B', 'UK', 'VIP']:
            normalized.append(g.upper())
        elif g.lower() == 'k-pop':
            normalized.append('K-Pop')
        elif '&' in g:
            # Handle "Drum & Bass" style
            parts = g.split('&')
            normalized.append(' & '.join(word.strip().capitalize() for word in parts))
        else:
            # Standard title case
            normalized.append(' '.join(word.capitalize() for word in g.split()))
    
    return ' / '.join(normalized)

async def query_soundcloud_genre(title, artist=None):
    """Query SoundCloud for track genre tag."""
    if not soundcloud_enabled:
        return None
    
    try:
        # Create async HTTP session and SoundCloud client
        async with aiohttp.ClientSession() as session:
            sc = SoundcloudAsyncAPI(
                client_id=SOUNDCLOUD_CLIENT_ID,
                auth_token=SOUNDCLOUD_AUTH_TOKEN,
                http_session=session
            )
            
            # Build search query with artist if available
            search_query = f"{artist} {title}" if artist else title
            
            # Search for the track on SoundCloud
            results = await sc.search(query_string=search_query, limit=5)
            
            # Handle dict response
            if isinstance(results, dict):
                collection = results.get('collection', [])
            else:
                collection = getattr(results, 'collection', [])
            
            if not collection:
                return None
            
            # Look for best match
            search_title_lower = title.lower()
            search_artist_lower = artist.lower() if artist else ""
            
            for idx, track in enumerate(collection):
                # Handle both dict and object responses
                if isinstance(track, dict):
                    kind = track.get('kind', '')
                    track_title_original = track.get('title', '')
                    track_title = track_title_original.lower()
                    track_artist = track.get('user', {}).get('username', '').lower() if isinstance(track.get('user'), dict) else ''
                    genre = track.get('genre', '')
                else:
                    kind = getattr(track, 'kind', '')
                    track_title_original = getattr(track, 'title', '')
                    track_title = track_title_original.lower()
                    track_user = getattr(track, 'user', None)
                    track_artist = getattr(track_user, 'username', '').lower() if track_user else ''
                    genre = getattr(track, 'genre', '')
                
                if kind == 'track':
                    # Check if it's a good match (keyword-based matching)
                    # Extract key words from search title (remove parentheses content)
                    search_keywords = search_title_lower.replace('(', ' ').replace(')', ' ').split()
                    search_keywords = [w for w in search_keywords if len(w) > 3]  # Filter short words
                    
                    # Count matching keywords in title
                    title_match_count = sum(1 for kw in search_keywords if kw in track_title)
                    
                    # Bonus points for artist match (if provided)
                    artist_match = False
                    if artist and search_artist_lower:
                        # Check if artist name appears in track artist or title
                        artist_keywords = search_artist_lower.split()
                        artist_match = any(kw in track_artist or kw in track_title for kw in artist_keywords if len(kw) > 2)
                    
                    # Require at least 2 matching keywords (reduced from 3 when artist is provided)
                    min_matches = 2 if artist else 3
                    
                    # Match if: enough title keywords match OR (some title matches + artist matches)
                    if title_match_count >= min_matches or (title_match_count >= 1 and artist_match):
                        if genre and genre.lower() not in ['', 'unknown', 'other']:
                            artist_info = f" by {track_artist}" if track_artist else ""
                            print(f"  🔊 SoundCloud: '{track_title_original[:40]}...'{artist_info} → Genre: {genre}")
                            # Return both genre and artist for validation (genre will be normalized later)
                            return (genre, track_artist)
            
            return None
    except Exception as e:
        print(f"  ⚠️ SoundCloud lookup failed: {e}")
        return None

def query_google_ai(title, chat, artist=None):
    """Ask Gemini for structured metadata for a given title with retry logic."""
    for attempt in range(MAX_RETRIES):
        try:
            # Include artist in query if available for more accurate genre identification
            if artist:
                query = f"Song title: {title}\nArtist: {artist}"
            else:
                query = f"Song title: {title}"
            response = chat.send_message(query)
            return response.text.strip()
        except Exception as e:
            error_str = str(e)
            
            # Check if it's a quota exhaustion error (429 RESOURCE_EXHAUSTED)
            if "429" in error_str and "RESOURCE_EXHAUSTED" in error_str:
                # Try to parse the retry delay from the error message
                retry_delay = 60  # Default to 60 seconds
                
                # Look for retryDelay in the error (format: 'retryDelay': '28s' or 'retryDelay': '28.549952853s')
                retry_match = re.search(r"'retryDelay':\s*'([\d.]+)s'", error_str)
                if retry_match:
                    # Parse as float and round up to nearest second
                    retry_delay = int(float(retry_match.group(1))) + 1
                
                if attempt < MAX_RETRIES - 1:  # Don't retry on last attempt
                    print(f"⏳ Quota exhausted for '{title}'. Waiting {retry_delay} seconds before retry (attempt {attempt + 1}/{MAX_RETRIES})...")
                    time.sleep(retry_delay)
                    continue  # Retry the request
                else:
                    print(f"❌ Google AI query failed for '{title}' after {MAX_RETRIES} attempts: {e}")
                    return None
            else:
                # For other errors, print and return None immediately
                print(f"❌ Google AI query failed for '{title}': {e}")
                return None
    
        return None

def validate_genre(genre_string, title, artist=None):
    """
    Validate genre and filter out vague/generic terms and artist/remixer names.
    Returns the validated genre string or None if too vague.
    """
    if not genre_string:
        return None
    
    # List of forbidden vague genres
    vague_genres = ["edm", "dance", "electronic", "club music", "music"]
    
    # List of forbidden compound vague terms (e.g., "Dance & EDM")
    forbidden_patterns = [
        r'\b(dance|edm|electronic)\b.*\b(dance|edm|electronic)\b',  # "Dance & EDM", "Electronic Dance", etc.
        r'\bedit\b$',  # "Edit" as a standalone genre
        r'\bmix\b$',   # "Mix" as a standalone genre  
        r'\bremix\b$', # "Remix" as a standalone genre
    ]
    
    # Extract remixer name from title to avoid using it as a genre
    remixer = extract_remixer_from_title(title)
    
    # Split by "/" for multi-genre tracks
    genres = [g.strip() for g in genre_string.split("/")]
    filtered_genres = []
    
    for genre in genres:
        genre_lower = genre.lower().strip()
        
        # Check if it's a vague genre
        if genre_lower in vague_genres:
            print(f"  ⚠️ Vague genre detected: '{genre}' - skipping this genre component")
            continue
        
        # Check for forbidden compound patterns
        is_forbidden_pattern = False
        for pattern in forbidden_patterns:
            if re.search(pattern, genre_lower):
                print(f"  ⚠️ Invalid genre pattern detected: '{genre}' - skipping")
                is_forbidden_pattern = True
                break
        if is_forbidden_pattern:
            continue
        
        # Check if the "genre" is actually the remixer's name
        if remixer and remixer.lower() in genre_lower:
            print(f"  ⚠️ Remixer name detected as genre: '{genre}' - skipping (remixer: {remixer})")
            continue
        
        # Check if the "genre" is actually the artist's name
        if artist and len(artist) > 3 and artist.lower() in genre_lower:
            print(f"  ⚠️ Artist name detected as genre: '{genre}' - skipping (artist: {artist})")
            continue
        
        # Allow "Club" if it's part of a compound genre like "Club House"
        # but reject standalone "Club" unless it came from Club Mix detection
        if genre_lower == "club":
            # This is handled separately by detect_club_mix(), skip here
            continue
            
        filtered_genres.append(genre)
    
    if not filtered_genres:
        print(f"  ❌ All genres were too vague for '{title}'. Marking as unknown.")
        return None
    
    return " / ".join(filtered_genres)

def sort_genre(genre_string):
    """Sort multi-genre strings alphabetically."""
    if "/" not in genre_string:
        return genre_string
    
    # Split by "/", strip whitespace, sort, and rejoin
    genres = [g.strip() for g in genre_string.split("/")]
    sorted_genres = sorted(genres, key=lambda x: x.lower())
    return " / ".join(sorted_genres)

def parse_response(response):
    """Extract is_remix, genre, artists, year, situation, and commercial friendly from the Gemini reply."""
    data = {}
    for line in response.splitlines():
        if line.startswith("Is Remix:"):
            is_remix = line.split(":", 1)[1].strip().lower()
            data["is_remix"] = is_remix == "yes"
        elif line.startswith("Genre:"):
            genre = line.split(":", 1)[1].strip()
            # Sort multi-genre alphabetically
            data["genre"] = sort_genre(genre)
        elif line.startswith("Original Artists:"):
            data["artists"] = line.split(":", 1)[1].strip()
        elif line.startswith("Original Song Release:"):
            data["year"] = line.split(":", 1)[1].strip()
        elif line.startswith("Situation:"):
            data["situation"] = line.split(":", 1)[1].strip()
        elif line.startswith("Commercial Friendly:"):
            data["commercial"] = line.split(":", 1)[1].strip()
    return data

def determine_energy_rating(genre, energy_map):
    """Return energy rating (1–5) based on genre. For multi-genre tracks, returns the highest energy level."""
    # Split by "/" to handle multi-genre tracks
    genres = [g.strip().lower() for g in genre.split('/')]
    
    found_ratings = []
    for single_genre in genres:
        matched = False
        
        # Pass 1: Try exact match first (e.g., "baile funk" matches "baile funk")
        for level, genre_list in energy_map.items():
            if single_genre in genre_list:
                found_ratings.append(int(level))
                matched = True
                break
        
        # Pass 2: If no exact match, try substring match (e.g., "deep house" contains "house")
        # Sort genre_list by length (longest first) to match most specific first
        if not matched:
            for level, genre_list in energy_map.items():
                sorted_genres = sorted(genre_list, key=len, reverse=True)
                if any(g in single_genre for g in sorted_genres):
                    found_ratings.append(int(level))
                    break
    
    # Return the highest energy level found, or None if no matches
    return max(found_ratings) if found_ratings else None

def apply_metadata(file_path, info, energy_map, unknown_genres):
    """Apply ID3 metadata and energy-based rating."""
    try:
        audio = EasyID3(file_path)
    except Exception:
        audio = MP3(file_path, ID3=EasyID3)
        audio.add_tags()

    genre = info.get("genre", "")
    artists = info.get("artists", "")
    year = info.get("year", "")

    if genre:
        # For ID3 tags, convert "/" to ";" for multi-genre support
        id3_genre = genre.replace(" / ", "; ").replace("/", "; ")
        audio["genre"] = id3_genre
    if artists:
        audio["artist"] = artists
    if year:
        audio["date"] = year

    audio.save()

    # Handle rating separately using ID3 POPM frame
    rating = None
    if genre:
        # Skip rating for mashups as they have varying energy levels
        if "mashup" in genre.lower():
            return None
        
        rating = determine_energy_rating(genre, energy_map)
        if rating is not None:
            # Use ID3 directly for rating (POPM frame)
            try:
                id3 = ID3(file_path)
                # Map 1-5 rating to 0-255 scale for POPM
                # 1=1-63, 2=64-127, 3=128-191, 4=192-223, 5=224-255
                rating_map = {1: 1, 2: 64, 3: 128, 4: 192, 5: 255}
                popm_rating = rating_map.get(rating, rating * 51)
                id3.add(POPM(email="rating@rekordbox", rating=popm_rating, count=0))
                id3.save()
            except Exception as e:
                print(f"⚠️ Failed to set rating for {file_path}: {e}")
        else:
            unknown_genres.append((os.path.basename(file_path), genre))

    return rating

def update_rekordbox_genre(track, genre_name, db):
    """Update the genre in Rekordbox database."""
    try:
        # Search for existing genre
        existing_genres = list(db.get_genre(Name=genre_name))
        
        if existing_genres:
            # Genre exists, use it
            genre = existing_genres[0]
        else:
            # Create new genre
            genre_id = db.generate_unused_id(tables.DjmdGenre)
            genre = tables.DjmdGenre.create(ID=genre_id, Name=genre_name)
            db.add(genre)
        
        # Update track's genre
        track.GenreID = genre.ID
        
    except Exception as e:
        print(f"  ⚠️ Failed to update Rekordbox genre: {e}")

def tag_rekordbox(file_path, title, situation, genre, rating, commercial, is_transition, db):
    """Assign MyTags ('Bar', 'Club', 'Commercial') to Rekordbox tracks, update genre and rating.
    Note: is_transition parameter is kept for future use but not currently used for tagging."""
    try:
        # Convert to absolute path to match Rekordbox database format
        abs_path = os.path.abspath(file_path).replace('\\', '/')
        
        # Search for the track by title (from ID3 tags)
        tracks = db.search_content(title)
        
        # Find exact match by path
        track = None
        for t in tracks:
            if t.FolderPath and abs_path == t.FolderPath:
                track = t
                break
        
        if not track:
            print(f"  ⚠️ Track not found in Rekordbox database: {title}")
            return

        # Clear all existing MyTag links for this track (reset tags)
        existing_song_tags = db.query(tables.DjmdSongMyTag).filter_by(ContentID=track.ID).all()
        if existing_song_tags:
            print(f"  🔄 Clearing {len(existing_song_tags)} existing tag(s) for: {title}")
            for song_tag in existing_song_tags:
                db.delete(song_tag)

        # Update genre in Rekordbox database
        if genre:
            update_rekordbox_genre(track, genre, db)
        
        # Update rating in Rekordbox database (skip if None, e.g., for mashups)
        if rating is not None:
            track.Rating = rating

        def ensure_tag(name, parent_name="Situation"):
            """Get or create a MyTag by name under a parent category."""
            # First check if tag already exists
            existing_tags = list(db.get_my_tag(Name=name))
            if existing_tags:
                return existing_tags[0]
            
            # Find the parent tag (e.g., "Situation")
            parent_tags = list(db.get_my_tag(Name=parent_name))
            parent_id = parent_tags[0].ID if parent_tags else None
            
            # Generate a unique ID for the new tag
            new_id = db.generate_unused_id(tables.DjmdMyTag)
            
            # Create new tag under parent with generated ID
            new_tag = tables.DjmdMyTag.create(ID=new_id, Name=name, ParentID=parent_id)
            db.add(new_tag)
            return new_tag

        tags_added = []
        situation_lower = situation.lower()
        
        # Check if we should add Bar tag
        should_add_bar = "bar" in situation_lower or situation_lower == "both"
        # Check if we should add Club tag
        should_add_club = "club" in situation_lower or situation_lower == "both"
        # Check if we should add Commercial tag
        should_add_commercial = commercial and commercial.lower() == "yes"
        
        if should_add_bar:
            bar_tag = ensure_tag("Bar")
            # Check if tag already linked
            if bar_tag.ID not in track.MyTagIDs:
                # Create junction table entry
                junction_id = db.generate_unused_id(tables.DjmdSongMyTag)
                song_tag = tables.DjmdSongMyTag.create(
                    ID=junction_id,
                    ContentID=track.ID,
                    MyTagID=bar_tag.ID
                )
                db.add(song_tag)
                tags_added.append("Bar")

        if should_add_club:
            club_tag = ensure_tag("Club")
            # Check if tag already linked
            if club_tag.ID not in track.MyTagIDs:
                # Create junction table entry
                junction_id = db.generate_unused_id(tables.DjmdSongMyTag)
                song_tag = tables.DjmdSongMyTag.create(
                    ID=junction_id,
                    ContentID=track.ID,
                    MyTagID=club_tag.ID
                )
                db.add(song_tag)
                tags_added.append("Club")

        if should_add_commercial:
            commercial_tag = ensure_tag("Commercial")
            # Check if tag already linked
            if commercial_tag.ID not in track.MyTagIDs:
                # Create junction table entry
                junction_id = db.generate_unused_id(tables.DjmdSongMyTag)
                song_tag = tables.DjmdSongMyTag.create(
                    ID=junction_id,
                    ContentID=track.ID,
                    MyTagID=commercial_tag.ID
                )
                db.add(song_tag)
                tags_added.append("Commercial")
        
        # Add genre tags under "Genre" parent
        if genre:
            # Split by " / " for multi-genre tracks (e.g., "Deep House / Tech House")
            genre_list = [g.strip() for g in genre.split('/')]
            
            for genre_name in genre_list:
                genre_tag = ensure_tag(genre_name, parent_name="Genre")
                # Check if tag already linked
                if genre_tag.ID not in track.MyTagIDs:
                    # Create junction table entry
                    junction_id = db.generate_unused_id(tables.DjmdSongMyTag)
                    song_tag = tables.DjmdSongMyTag.create(
                        ID=junction_id,
                        ContentID=track.ID,
                        MyTagID=genre_tag.ID
                    )
                    db.add(song_tag)
                    tags_added.append(f"Genre:{genre_name}")
            
    except Exception as e:
        import traceback
        print(f"  ⚠️ Rekordbox tagging failed: {e}")
        print(f"  Full error traceback:")
        traceback.print_exc()
        raise  # Re-raise to stop execution

# -------------------- MAIN --------------------
def main():
    # Check if Rekordbox is running FIRST before any processing
    print("=" * 60)
    print("🚨 IMPORTANT: Rekordbox MUST be closed for tagging to work!")
    print("=" * 60)
    
    try:
        db_test = Rekordbox6Database()
        # If we get here, check if Rekordbox is actually running
        # Try a simple operation to see if database is locked
        try:
            test_content = list(db_test.get_content())[:1]
            db_test.close()
        except Exception as e:
            db_test.close()
            if "running" in str(e).lower():
                print("\n❌ ERROR: Rekordbox is currently running!")
                print("   Please close Rekordbox completely and run the script again.")
                return
    except Exception as e:
        print(f"⚠️ Could not connect to Rekordbox database: {e}")
        print("   Will continue with ID3 tagging only...\n")
    
    print("✓ Rekordbox check passed\n")
    
    energy_map = load_json(ENERGY_MAP_PATH)
    processed_songs = load_json(PROCESSED_SONGS_PATH)
    unknown_genres = []
    missing_title_files = []
    failed_files = []  # Track files that failed after all retries

    # First pass: collect files that need processing
    files_to_process = []
    low_bitrate_files = []

    for root, _, files in os.walk(MUSIC_DIR):
        for file in files:
            if not file.lower().endswith(".mp3"):
                continue

            full_path = os.path.join(root, file)
            bitrate = get_bitrate(full_path)
            if bitrate < BITRATE_MIN:
                low_bitrate_files.append((file, bitrate))
                continue

            # Retrieve title from ID3 tag
            try:
                audio = EasyID3(full_path)
                title_list = audio.get("title")
                if title_list:
                    title = title_list[0]
                    # Skip already processed
                    if title not in processed_songs:
                        files_to_process.append((full_path, title))
                else:
                    missing_title_files.append(file)
            except Exception as e:
                missing_title_files.append(file)
    
    # If no files to process, exit early
    if not files_to_process:
        print("No new files to process.")
        
        if low_bitrate_files:
            print("\n⚠️ Files skipped (low bitrate):")
            for file, bitrate in low_bitrate_files:
                print(f"  - {file}: {bitrate/1000:.1f} kbps")
        
        if missing_title_files:
            print("\n⚠️ Files missing title metadata:")
            for f in missing_title_files:
                print(f"  - {f}")
        return
    
    print(f"Found {len(files_to_process)} file(s) to process.\n")
    
    # Show SoundCloud status
    if soundcloud_enabled:
        print("✓ SoundCloud genre lookup: ENABLED")
    else:
        print("⊙ SoundCloud genre lookup: DISABLED (add credentials to enable)")
    print()
    
    # Initialize Rekordbox database for actual processing
    try:
        db = Rekordbox6Database()
        rekordbox_enabled = True
        print("✓ Rekordbox database connection established\n")
    except Exception as e:
        print(f"⚠️ Rekordbox database unavailable: {e}")
        print("   Continuing with ID3 tagging only...\n")
        rekordbox_enabled = False
        db = None

    # Start persistent chat session (NEW API)
    chat = client.chats.create(model="gemini-2.5-flash-lite")
    
    # Send initial prompt with retry logic
    for attempt in range(MAX_RETRIES):
        try:
            chat.send_message(PROMPT_INSTRUCTIONS)
            break  # Success, exit retry loop
        except Exception as e:
            error_str = str(e)
            
            # Check if it's a quota exhaustion error (429 RESOURCE_EXHAUSTED)
            if "429" in error_str and "RESOURCE_EXHAUSTED" in error_str:
                # Try to parse the retry delay from the error message
                retry_delay = 60  # Default to 60 seconds
                
                # Look for retryDelay in the error (format: 'retryDelay': '3s' or 'retryDelay': '3.423771862s')
                retry_match = re.search(r"'retryDelay':\s*'([\d.]+)s'", error_str)
                if retry_match:
                    # Parse as float and round up to nearest second
                    retry_delay = int(float(retry_match.group(1))) + 1
                
                if attempt < MAX_RETRIES - 1:  # Don't retry on last attempt
                    print(f"⏳ Quota exhausted during initialization. Waiting {retry_delay} seconds before retry (attempt {attempt + 1}/{MAX_RETRIES})...")
                    time.sleep(retry_delay)
                    continue  # Retry the request
                else:
                    print(f"❌ Failed to initialize chat after {MAX_RETRIES} attempts: {e}")
                    print("   Please wait for quota reset and try again later.")
                    return
            else:
                # For other errors, print and exit
                print(f"❌ Failed to initialize chat: {e}")
                return

    try:
        for idx, (full_path, title) in enumerate(tqdm(files_to_process, desc="Processing files")):
            # Add delay between requests to respect rate limits (skip for first request)
            if idx > 0:
                time.sleep(API_DELAY_SECONDS)
            
            # Extract artist from metadata for better genre accuracy
            artist = get_artist_from_file(full_path)
            
            # Query Google AI for metadata first (include artist if available)
            response = query_google_ai(title, chat, artist)
            if not response:
                failed_files.append((title, "API query failed after all retries"))
                continue

            info = parse_response(response)
            is_remix = info.get("is_remix", False)
            
            # Store original Gemini genre as fallback
            gemini_genre = info.get("genre", "")
            
            # Only check SoundCloud if it's a REMIX (remixes should use remixer's genre tags)
            # Original songs should keep their original genre from Gemini
            if is_remix:
                # PRIORITY 1: Check if genre is explicitly in the remix title
                title_genre = extract_genre_from_remix_title(title, energy_map)
                if title_genre:
                    info["genre"] = title_genre
                    print(f"  🎵 Genre found in title: {title_genre}")
                # PRIORITY 2: Query SoundCloud for remixer's genre
                elif soundcloud_enabled:
                    try:
                        # For remixes, extract REMIXER name from title (e.g., "Song (Ale Lucchi Remix)" -> "Ale Lucchi")
                        # This is more accurate than using the original artist
                        remixer = extract_remixer_from_title(title)
                        
                        if remixer:
                            print(f"  🎧 Detected remixer: {remixer}")
                            sc_result = asyncio.run(query_soundcloud_genre(title, remixer))
                            
                            if sc_result:
                                sc_genre, sc_artist = sc_result
                                
                                # Validate: Check if remixer name appears in SoundCloud artist name
                                remixer_lower = remixer.lower()
                                sc_artist_lower = sc_artist.lower() if sc_artist else ""
                                
                                # Split remixer name into keywords for matching
                                remixer_keywords = remixer_lower.split()
                                # Check if any significant keyword from remixer appears in SC artist
                                remixer_match = any(kw in sc_artist_lower for kw in remixer_keywords if len(kw) > 2)
                                
                                if remixer_match:
                                    info["genre"] = sc_genre
                                    print(f"  ✓ Using SoundCloud genre for remix: {sc_genre}")
                                else:
                                    print(f"  ⚠️ SoundCloud artist mismatch: '{sc_artist}' ≠ '{remixer}' - using Gemini genre")
                        else:
                            print(f"  ℹ️ Could not extract remixer - using Gemini genre")
                            
                    except Exception as e:
                        print(f"  ⚠️ SoundCloud error: {e}")
            else:
                print(f"  ℹ️ Original song - using genre from AI: {info.get('genre')}")
            
            # Validate genre to filter out vague terms and artist/remixer names
            if info.get("genre"):
                validated_genre = validate_genre(info["genre"], title, artist)
                if not validated_genre:
                    # Current genre was too vague, try fallback to Gemini genre if different
                    if gemini_genre and gemini_genre.lower() != info.get("genre", "").lower():
                        print(f"  🔄 Falling back to Gemini genre: {gemini_genre}")
                        validated_genre = validate_genre(gemini_genre, title, artist)
                        if not validated_genre:
                            # Both genres were too vague, skip this track
                            print(f"  ⚠️ Both SoundCloud and Gemini genres were invalid - skipping")
                            continue
                        info["genre"] = validated_genre
                    else:
                        # No valid fallback, skip this track
                        continue
                else:
                    info["genre"] = validated_genre
            
            # Normalize genre to Title Case for consistency
            if info.get("genre"):
                info["genre"] = normalize_genre_case(info["genre"])
            
            # Detect and append Club to genre if "Club Mix" pattern found in title
            is_club_mix = detect_club_mix(title)
            if is_club_mix and info.get("genre"):
                # Only append if "club" is not already present in the genre
                if "club" not in info["genre"].lower():
                    info["genre"] = f"{info['genre']} / Club"
                    print(f"  🎶 Club mix detected - Genre updated to: {info['genre']}")
            
            # Detect and append Transition to genre if BPM pattern found
            is_transition = detect_transition(title)
            if is_transition and info.get("genre"):
                # Only append if not already present
                if "transition" not in info["genre"].lower():
                    info["genre"] = f"{info['genre']} / Transition"
                    print(f"  🔄 Transition track detected - Genre updated to: {info['genre']}")
            
            genre = info.get("genre", "").lower()
            if genre == "unknown" or not genre:
                print(f"  ⚠️ No valid genre found for '{title}' - skipping (will reprocess later)")
                continue  # skip if unknown

            rating = apply_metadata(full_path, info, energy_map, unknown_genres)
            
            # Check if rating was determined (None means genre not in energy map or mashup)
            # Mashups are allowed (valid genre but no rating due to varying energy)
            is_mashup = "mashup" in genre
            
            if rating is None and not is_mashup:
                # Genre not found in energy map - this is an unknown/invalid genre
                print(f"  ⚠️ Unknown genre for '{title}': '{info.get('genre')}' - not found in energy map")
                print(f"     Skipping Rekordbox tagging and not marking as processed (will reprocess later)")
                continue  # Skip this track entirely - don't tag or mark as processed
            
            # Tag in Rekordbox if database is available
            if rekordbox_enabled and db:
                try:
                    tag_rekordbox(full_path, title, info.get("situation", ""), info.get("genre", ""), rating, info.get("commercial", ""), is_transition, db)
                    # Commit to database immediately after tagging
                    db.commit()
                except Exception as e:
                    print(f"  ⚠️ Failed to tag/commit to Rekordbox: {e}")
                    # Don't skip - still save to processed_songs if ID3 tagging succeeded

            # Only mark as processed if genre was valid
            processed_songs[title] = True
            
            # Save processed_songs.json immediately after each successful song
            save_json(PROCESSED_SONGS_PATH, processed_songs)

            commercial_status = f"\n  Commercial: {info.get('commercial')}" if info.get('commercial') else ""
            remix_status = " [REMIX]" if info.get('is_remix') else " [ORIGINAL]"
            rating_display = rating if rating is not None else "N/A (Mashup)"
            print(f"\n✅ Tagged: {title}{remix_status}\n  Genre: {info.get('genre')}\n  Rating: {rating_display}\n  Situation: {info.get('situation')}{commercial_status}")

        # Final commit (safety - individual commits already done per song)
        if rekordbox_enabled and db:
            try:
                db.commit()
                print("\n✓ Final Rekordbox database commit successful!")
            except RuntimeError as e:
                print(f"\n❌ Failed final commit: {e}")
                print("   Please close Rekordbox and run the script again.")
            except Exception as e:
                print(f"\n❌ Failed final commit: {e}")
    
    finally:
        # Close database connection
        if db:
            db.close()
            print("✓ Rekordbox database connection closed")

    # Note: processed_songs.json is saved after each song, no final save needed
    print(f"✓ All progress saved to {PROCESSED_SONGS_PATH}")

    # Print summary of issues/warnings
    if low_bitrate_files or missing_title_files or unknown_genres or failed_files:
        print("\n" + "=" * 60)
        print("SUMMARY OF ISSUES")
        print("=" * 60)

    if failed_files:
        print(f"\n❌ Files failed after retries: {len(failed_files)}")
        for title, reason in failed_files:
            print(f"  - {title} → {reason}")
        print(f"\n💡 Tip: Wait for quota reset and run the script again to process failed files.")

    if low_bitrate_files:
        print(f"\n⚠️ Files skipped (low bitrate < {BITRATE_MIN/1000:.0f} kbps): {len(low_bitrate_files)}")
        for file, bitrate in low_bitrate_files:
            print(f"  - {file}: {bitrate/1000:.1f} kbps")

    if missing_title_files:
        print(f"\n⚠️ Files missing title metadata: {len(missing_title_files)}")
        for f in missing_title_files:
            print(f"  - {f}")

    if unknown_genres:
        print(f"\n⚠️ Songs with unknown/invalid genres (NOT PROCESSED): {len(unknown_genres)}")
        print(f"   These songs were NOT tagged or saved to processed_songs.json")
        print(f"   They will be reprocessed on the next run.")
        for title, genre in unknown_genres:
            print(f"  - {title} → {genre}")
        print(f"\n💡 Tip: Add these genres to energy_map.json or update the AI prompt to get more specific genres.")

if __name__ == "__main__":
    main()
