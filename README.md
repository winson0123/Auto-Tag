# Auto-Tag for Rekordbox

Automatically tag your DJ music library with genres, ratings, and situation tags using AI and SoundCloud API.

## Features

- 🎵 **Genre Classification** - Uses Google Gemini AI + optional SoundCloud API for accurate genre tagging
- ⭐ **Energy-Based Ratings** - Automatically rates tracks 1-5 based on genre energy levels
- 🏷️ **Situation Tags** - Tags tracks as Bar, Club, or Both for easy filtering
- ✅ **Commercial Friendly** - Identifies clean/radio-friendly tracks
- 🔄 **Transition Detection** - Automatically detects and tags transition tracks (BPM patterns like "128-94")
- 📊 **Rekordbox Integration** - Direct database updates (genre, rating, MyTags)
- 🔀 **Multi-Genre Support** - Handles tracks with multiple genres, sorted alphabetically
- ⏱️ **Rate Limiting** - Automatic retry and delay handling for API quotas

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. (Optional) Install SoundCloud support for more accurate genre tagging:
```bash
pip install soundcloudpy
```

## Configuration

### Method 1: Environment Variables (Recommended)

Set environment variables in your system:

**Windows (PowerShell):**
```powershell
$env:GENAI_API_KEY = "your_api_key_here"
$env:MUSIC_DIR = "C:\Path\To\Your\Music\Library"
$env:SOUNDCLOUD_CLIENT_ID = "your_client_id"  # Optional
$env:SOUNDCLOUD_AUTH_TOKEN = "OAuth 2-xxxxx-xxxxx-xxxxxxxxx"  # Optional
```

**Windows (Command Prompt):**
```cmd
set GENAI_API_KEY=your_api_key_here
set MUSIC_DIR=C:\Path\To\Your\Music\Library
```

**Linux/Mac:**
```bash
export GENAI_API_KEY="your_api_key_here"
export MUSIC_DIR="/path/to/your/music/library"
```

### Method 2: Direct Configuration

Alternatively, edit the configuration section in `auto_tag_rekordbox.py` (lines 24-34):

```python
MUSIC_DIR = r"C:\Path\To\Your\Music\Library"
GENAI_API_KEY = "your_api_key_here"
SOUNDCLOUD_CLIENT_ID = "your_client_id"  # Optional
SOUNDCLOUD_AUTH_TOKEN = "OAuth 2-xxxxx-xxxxx-xxxxxxxxx"  # Optional
```

### Required: Google Gemini API

1. Get a free API key from [Google AI Studio](https://aistudio.google.com/apikey)
2. Set it using environment variable `GENAI_API_KEY` or directly in the config

### Optional: SoundCloud API (Highly Recommended!)

For **much more accurate** genre detection using producer/remixer's own SoundCloud tags:

1. Go to [SoundCloud](https://soundcloud.com) and **log in**
2. Press **F12** to open Developer Tools
3. Click the **Network** tab
4. **Refresh** the page (F5)
5. In the Network tab, click on any request and look in the **Headers** section:
   - **client_id**: Found in request URLs (32-character alphanumeric)
   - **Authorization**: Found in Request Headers (format: `OAuth 2-xxxxx-xxxxx-xxxxxxxxx`)
6. Set via environment variables or update directly in the config

**Why use SoundCloud?**
- Gets genre directly from the producer's own track tags (e.g., "Afro House" from Ale Lucchi)
- Much more accurate than AI guessing
- Prioritized over Gemini AI results

## Usage

1. **Close Rekordbox** (important!)
2. Update `MUSIC_DIR` path in the script
3. Run:
```bash
python auto_tag_rekordbox.py
```

## How It Works

1. Scans your music directory for MP3 files
2. For each track:
   - **Extracts artist** from ID3 metadata
   - **Queries Google Gemini** with artist + title for accurate genre analysis
   - **Determines if remix or original** using AI
   - **IF REMIX**: 
     - Extracts remixer name from title
     - Queries SoundCloud with "Remixer + Title"
     - **Validates** remixer matches SoundCloud uploader (prevents false matches)
     - Falls back to Gemini if no match or validation fails
   - **IF ORIGINAL**: Uses Gemini's genre (includes artist context for accuracy)
   - Determines energy rating (1-5) based on genre with exact + substring matching
   - Updates ID3 tags (genre, artist, year, rating)
   - Updates Rekordbox database (genre, rating, situation tags)
3. Displays summary of processed tracks and any issues

**Smart Genre Logic:**
- **Remixes** → Uses remixer's SoundCloud tags (e.g., Pop song remixed as Afro House = Afro House)
- **Originals** → Uses original genre from Gemini (e.g., IU's "Soda Pop" stays K-Pop/Pop)
- **All genres** → Normalized to Title Case for consistency (e.g., "tech house" → "Tech House")

**Genre Priority for Remixes:**
1. 🥇 **Genre in Title** - If title contains genre name (e.g., "Esquire Afro House Remix" → "Afro House")
2. 🥈 **SoundCloud** - Remixer's own tags with validation (only for remixes)
3. 🥉 **Gemini AI** - AI inference if above methods don't find genre

**Genre for Originals:**
- Uses Gemini's analysis of the original song's genre (with artist context)

**Matching Improvements:**
- **Genre extraction from title**: Automatically detects 120+ genres from `energy_map.json` in remix titles
- **Remixer-aware search**: Extracts remixer name from title (e.g., "Song (Ale Lucchi Remix)" → searches "Ale Lucchi")
- **Original artist from metadata**: Only uses ID3 artist tag (no unreliable filename parsing)
- Exact genre matching before substring matching (e.g., "Baile Funk" won't match as "Funk")
- Normalizes all genres to Title Case with special handling for acronyms (DNB, R&B, UK, K-Pop)

**Transition Detection:**
- **Automatic BPM Pattern Detection**: Finds patterns like "128-94", "130-100" in track titles
- **Genre Enhancement**: Appends "/ Transition" to genre (e.g., "Hip-hop" → "Hip-hop / Transition")
- **Genre Tagging**: Creates "Transition" tag under Genre category for easy filtering
- **Smart Rating**: Uses base genre energy for rating (e.g., "Hip-hop / Transition" rated as Hip-hop)

## Genre Energy Map

Edit `energy_map.json` to customize how genres map to energy ratings (1-5).

## Rate Limits

- **Gemini Free Tier**: 10 requests/minute (script uses 7-second delays)
- **Automatic Retry**: Handles quota errors with exponential backoff
- **SoundCloud**: No rate limiting by default

## Rekordbox Tags Created

### Under **Situation** category:
- **Bar** - Laid-back/moderate energy tracks
- **Club** - High-energy dance tracks  
- **Commercial** - Clean/radio-friendly tracks

### Under **Genre** category:
- Automatically creates tags for each genre (e.g., "Deep House", "Tech House")
- Multi-genre tracks get multiple tags (e.g., "Deep House / Tech House" creates both "Deep House" and "Tech House" tags)
- Transition tracks get "Transition" genre tag (e.g., "Hip-hop / Transition" creates both "Hip-hop" and "Transition" tags)
- All tracks are linked to their genre tags for easy filtering

### Tag Reset Feature:
- **Automatic Cleanup**: When reprocessing a track, all existing MyTag links are automatically cleared first
- **No Duplicates**: Ensures clean tagging without old/outdated tags lingering
- **Safe Reprocessing**: You can safely rerun the script on already-tagged tracks to update them

## Credits

- [pyrekordbox](https://github.com/dylanljones/pyrekordbox) - Rekordbox database access
- [SoundcloudPy](https://github.com/music-assistant/SoundcloudPy) - SoundCloud API client
- [Google Gemini](https://ai.google.dev/) - AI-powered metadata generation

## License

MIT License - Feel free to use and modify!

