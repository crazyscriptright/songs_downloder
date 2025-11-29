# Universal Music Downloader

![Homepage Preview](.github/homepage.png)

A powerful web-based music downloader that searches and downloads music from multiple sources including YouTube Music, JioSaavn, and SoundCloud.

[![Deploy to Heroku](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy)

## Features

- **Multi-Source Search**: Search across YouTube Music, YouTube Videos, JioSaavn, and SoundCloud simultaneously
- **Web Interface**: Clean, modern web interface with real-time search results
- **Advanced Download Options**: Customizable audio quality, format selection, and metadata embedding
- **Progress Tracking**: Real-time download progress with speed and ETA information
- **URL Support**: Direct download from supported platform URLs
- **Background Processing**: Non-blocking downloads with queue management
- **Security Features**: Input validation and command injection prevention

## Supported Platforms

- YouTube Music
- YouTube Videos
- JioSaavn
- SoundCloud
- Spotify (URL validation only)

## Quick Deploy to Heroku

Click the button above or follow the detailed guide in [HEROKU_DEPLOY.md](HEROKU_DEPLOY.md).

**Important:**

- Heroku has read-only filesystem (except `/tmp`)
- App automatically uses `/tmp` for downloads when on Heroku
- Downloaded files are **temporary** and deleted on dyno restart
- Users must download files immediately after processing

## Local Installation

### Prerequisites

- **Python 3.11** (recommended)
- Google Chrome browser installed
- Internet connection for downloading

### Setup

1. Clone or download the project files

2. Install Python dependencies:

   ```bash
   pip install flask yt-dlp requests python-dotenv selenium
   ```

3. Install Chrome WebDriver:

   ```bash
   # Option 1: Using webdriver-manager (recommended)
   pip install webdriver-manager

   # Option 2: Manual installation
   # Download ChromeDriver from https://chromedriver.chromium.org/
   # Extract and add to your system PATH
   ```

4. Alternative: Install from requirements.txt (manual driver setup needed):
   ```bash
   pip install -r requirements.txt
   # Note: You'll need to manually install ChromeDriver for selenium
   ```

### Configuration

1. Create a `.env` file (optional) for environment variables
2. Configure download folder (defaults to ~/Downloads/Music)
3. Set up API tokens if needed for enhanced functionality

## Usage

### Starting the Server

Run the main application:

```
python web_main.py
```

The server will start on `http://localhost:5000`

### Web Interface

1. **Search**: Enter song name, artist, or direct URL
2. **Select Source**: Choose between Music, Video, or All sources
3. **Browse Results**: View results from all sources with thumbnails and metadata
4. **Download**: Click download button and optionally configure advanced settings
5. **Monitor Progress**: Track download progress in real-time
6. **Manage Downloads**: Cancel, clear, or download completed files

### Advanced Download Options

- **Audio Format**: MP3, M4A, OPUS, VORBIS, WAV, FLAC
- **Audio Quality**: 0 (best) to 9 (worst)
- **Video Options**: Keep video, resolution selection, FPS control
- **Metadata**: Embed metadata and thumbnails
- **Custom Arguments**: Advanced yt-dlp parameters

## File Structure

```
songdownload/
├── web_main.py                    # Main Flask application
├── templates/
│   └── index.html                 # Web interface template
├── ytmusic_dynamic_tokens.py      # YouTube Music API handler
├── ytmusic_dynamic_video_tokens.py # YouTube Video API handler
├── jiosaavn_search.py            # JioSaavn API integration
├── soundcloud.py                 # SoundCloud search functionality
├── requirements.txt              # Python dependencies
├── .env                          # Environment variables (optional)
└── README.md                     # This file
```

## Credits

This project is powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp) - thanks to the yt-dlp team for their excellent tool that makes downloading from various platforms possible.

## License

This project is for educational and personal use only. Respect copyright laws and platform terms of service.

## Disclaimer

Users are responsible for complying with applicable laws and platform terms of service. This tool is intended for downloading content you have rights to access.
