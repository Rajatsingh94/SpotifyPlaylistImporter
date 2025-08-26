# SpotifyPlaylistImporter

Python script to Create and Import Playlist in Spotify from Apple Music

---

## Features
- Parse Apple Music/iTunes XML exports
- Create a new Spotify playlist **or** update an existing one
- Add tracks automatically (with basic search matching)
- Supports **append** or **replace** mode for existing playlists

---

## Requirements
- Python **3.9+**  
- [Spotify Developer App](https://developer.spotify.com/dashboard/) with:
  - **Client ID**
  - **Client Secret**
  - Redirect URI: `http://localhost:8888/callback`

---

## Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/Rajatsingh94/SpotifyPlaylistImporter.git
   cd SpotifyPlaylistImporter

2. Create and activate a virtual environment (recommended):
	```bash	
 	python3 -m venv .venv
 	source .venv/bin/activate

3. Install dependencies:
	```bash
 	pip install -r requirements.txt

4. Export your Apple Music playlist:
    ```bash
    Open Apple Music → File → Library → Export Playlist… → Save as MyPlaylist.xml

5. Set your Spotify credentials as environment variables:
   ```bash
   export SPOTIPY_CLIENT_ID="your_client_id"
   export SPOTIPY_CLIENT_SECRET="your_client_secret"
   export SPOTIPY_REDIRECT_URI="http://localhost:8888/callback"

___

## Usage

1. Create a new playlist on Spotify:
   ```bash
	python3 apple_xml_to_spotify.py \
	--xml "MyPlaylist.xml" \
	--spotify-name "My Imported Playlist"

2. Add songs to an existing playlist:
	```bash
	python3 apple_xml_to_spotify.py \
  	--xml "MyPlaylist.xml" \
  	--use-existing "My Spotify Playlist"


3. Replace all songs in an existing playlist:
	```bash
	python3 apple_xml_to_spotify.py \
  	--xml "MyPlaylist.xml" \
  	--use-existing "My Spotify Playlist" \
  	--mode replace

___

## License:
GPL-3.0



