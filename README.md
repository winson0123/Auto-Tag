# Auto-Tag for Rekordbox

Automatically tag your DJ music library with genres, ratings, and situation tags using AI and SoundCloud API.

## Features

- 🎵 **Genre Classification** - Uses Google Gemini AI + optional SoundCloud API for accurate genre tagging
- 🛡️ **Genre Validation** - Filters out vague genres (EDM, Dance, Electronic) and artist/remixer names
- 🔄 **Smart Fallback** - Automatically falls back to Gemini genre if SoundCloud returns invalid genres
- ⭐ **Energy-Based Ratings** - Automatically rates tracks 1-5 based on genre energy levels
- 🏷️ **Situation Tags** - Tags tracks as Bar, Club, or Both for easy filtering
- ✅ **Commercial Friendly** - Identifies clean/radio-friendly tracks
- 🎶 **Club Mix Detection** - Automatically detects and tags club mix tracks
- 🔄 **Transition Detection** - Automatically detects and tags transition tracks (BPM patterns like "128-94")
- 📊 **Rekordbox Integration** - Direct database updates (genre, rating, MyTags)
- 🔀 **Multi-Genre Support** - Handles tracks with multiple genres, sorted alphabetically
- 💾 **Incremental Saves** - Saves progress after each song (crash recovery)
- 🌍 **UTF-8 Support** - Handles Unicode characters (Japanese, Korean, etc.)
- ⏱️ **Rate Limiting** - Automatic retry with dynamic delay from API response
- 🔁 **Auto-Retry** - Songs with invalid genres are automatically reprocessed on next run

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

### Method 1: .env File (Recommended)

1. Copy the example environment file:
```bash
cp env.example .env
```

2. Edit `.env` and fill in your configuration:
```env
MUSIC_DIR=C:\Path\To\Your\Music\Library
GENAI_API_KEY=your_gemini_api_key_here
SOUNDCLOUD_CLIENT_ID=your_client_id  # Optional
SOUNDCLOUD_AUTH_TOKEN=OAuth 2-xxxxx-xxxxx-xxxxxxxxx  # Optional
```

The script will automatically load these environment variables using python-dotenv.

### Method 2: System Environment Variables

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

### Method 3: Direct Configuration

Alternatively, edit the configuration section in `auto_tag_rekordbox.py` (lines 28-38):

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

1. Scans your music directory for MP3 files (skips already processed songs from `processed_songs.json`)
2. For each track:
   - **Extracts artist** from ID3 metadata
   - **Queries Google Gemini** with artist + title for accurate genre analysis
   - **Determines if remix or original** using AI
   - **IF REMIX**: 
     - Extracts remixer name from title
     - Queries SoundCloud with "Remixer + Title"
     - **Validates** remixer matches SoundCloud uploader (prevents false matches)
     - If valid, uses SoundCloud genre; if invalid, falls back to Gemini
   - **IF ORIGINAL**: Uses Gemini's genre (includes artist context for accuracy)
   - **Validates genre**:
     - Filters out vague genres: "EDM", "Dance", "Electronic", "Club Music"
     - Filters out compound vague terms: "Dance & EDM"
     - Rejects artist/remixer names used as genres
     - If SoundCloud genre is invalid, automatically falls back to Gemini genre
     - Skips tracks with no valid genre (will reprocess on next run)
   - **Detects special patterns**:
     - Club Mix (adds "Club" to genre)
     - Transition tracks (adds "Transition" to genre)
   - Determines energy rating (1-5) based on genre with exact + substring matching
   - **Updates ID3 tags** (genre, artist, year, rating)
   - **Updates Rekordbox database** (genre, rating, situation tags)
   - **Commits to database immediately** (crash recovery)
   - **Saves to processed_songs.json immediately** (progress tracking)
3. Displays summary of processed tracks and any issues

**Smart Genre Logic:**
- **Remixes** → Uses remixer's SoundCloud tags (e.g., Pop song remixed as Afro House = Afro House)
- **Originals** → Uses original genre from Gemini (e.g., IU's "Soda Pop" stays K-Pop/Pop)
- **All genres** → Normalized to Title Case for consistency (e.g., "tech house" → "Tech House")

**Genre Priority for Remixes:**
1. 🥇 **Genre in Title** - If title contains genre name (e.g., "Esquire Afro House Remix" → "Afro House")
2. 🥈 **SoundCloud** - Remixer's own tags with validation (only for remixes)
   - Must pass validation (filters vague genres, artist names)
   - Falls back to Gemini if invalid
3. 🥉 **Gemini AI** - AI inference with enhanced prompt to avoid vague terms

**Genre for Originals:**
- Uses Gemini's analysis of the original song's genre (with artist context)
- Validates and filters vague genres before accepting

**Genre Validation Rules:**
- ❌ **Rejects**: "EDM", "Dance", "Electronic", "Club Music", "Dance & EDM", "Music"
- ❌ **Rejects**: Artist/remixer names as genres (e.g., "Barbangerz", "Porter Robinson")
- ❌ **Rejects**: Genres not found in `energy_map.json`
- ✅ **Accepts**: Specific genres like "Tech House", "Afro House", "Progressive House", etc.
- 🔄 **Auto-retry**: Skipped songs are not marked as processed and will retry on next run

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

**Club Mix Detection:**
- **Automatic Pattern Detection**: Finds "Club Mix", "Club Version", "Club Edit", "Club Remix" in titles
- **Genre Enhancement**: Appends "/ Club" to genre (e.g., "Pop" → "Pop / Club")
- **Smart Tagging**: Ensures club mixes are properly categorized

## Crash Recovery & Progress Tracking

The script saves progress **after each successful song**, ensuring no data loss if interrupted:

- **Incremental Database Commits**: Rekordbox database is committed after each song
- **Real-time JSON Updates**: `processed_songs.json` is saved after each song
- **Resume from Interruption**: If script crashes or is stopped (Ctrl+C), next run continues from where it left off
- **Skipped Songs Auto-Retry**: Songs with invalid genres are NOT saved to `processed_songs.json` and will be reprocessed on next run
- **Progress Visibility**: Check `processed_songs.json` anytime to see what's been completed

**Example Recovery Scenario:**
1. Processing 100 songs, crashes after song 50
2. ✅ Songs 1-50: Saved in Rekordbox + `processed_songs.json`
3. ❌ Songs 51-100: Not processed
4. Next run: Automatically skips songs 1-50, resumes from song 51

## Genre Energy Map

Edit `energy_map.json` to customize how genres map to energy ratings (1-5).

**Expanded Genre Coverage (120+ genres):**
- **Energy 1** (Chill): Lofi, Jazz, R&B, Country, Acoustic, etc.
- **Energy 2** (Laid-back): Deep House, Disco, Funk, Reggae, Nu Disco, etc.
- **Energy 3** (Moderate): Pop, Dance-Pop, Progressive House, Afro House, Breaks, Club, etc.
- **Energy 4** (High): Tech House, Trap, Hip-Hop, Jersey Club, Trance, etc.
- **Energy 5** (Maximum): Hardstyle, Drum & Bass, Dubstep, Bass House, Techno, etc.

**Recent Additions:**
- Country, Bluegrass, Americana (Energy 1)
- Reggae, Dub, Roots Reggae, Reggae Fusion (Energy 2)
- Afro, Baile, Breaks, Club, Club House (Energy 3)
- Jersey, Miami Bass (Energy 4)

## Rate Limits

- **Gemini Free Tier**: 10 requests/minute, 250 requests/day (script uses 7-second delays)
- **Dynamic Retry Delay**: Automatically extracts and uses exact retry delay from API error responses
  - Example: API says "retry in 28.5s" → Script waits 29 seconds
  - Respects API's recommended retry timing for faster recovery
- **Automatic Retry**: Up to 5 retries with smart delay handling
- **SoundCloud**: No rate limiting by default

**What happens when quota is hit:**
1. Script detects quota exhaustion (429 error)
2. Extracts exact retry delay from API response
3. Displays countdown: `⏳ Quota exhausted. Waiting 29 seconds before retry (attempt 1/5)...`
4. Automatically retries after waiting
5. Resumes processing seamlessly

## Rekordbox Tags Created

### Under **Situation** category:
- **Bar** - Laid-back/moderate energy tracks
- **Club** - High-energy dance tracks  
- **Commercial** - Clean/radio-friendly tracks

### Under **Genre** category:
- Automatically creates tags for each genre (e.g., "Deep House", "Tech House")
- Multi-genre tracks get multiple tags (e.g., "Deep House / Tech House" creates both "Deep House" and "Tech House" tags)
- Transition tracks get "Transition" genre tag (e.g., "Hip-hop / Transition" creates both "Hip-hop" and "Transition" tags)
- Club mixes get "Club" genre tag (e.g., "Pop / Club" creates both "Pop" and "Club" tags)
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

