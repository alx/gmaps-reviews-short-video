import os
import pathlib
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]
TOKEN_PATH = pathlib.Path.home() / ".config" / "reviewreel" / "token.json"


def authenticate():
    """Return an authenticated YouTube API service, prompting OAuth if needed."""
    secrets_path = os.environ.get("YOUTUBE_CLIENT_SECRETS")
    if not secrets_path or not os.path.exists(secrets_path):
        print(
            "Error: YOUTUBE_CLIENT_SECRETS not set or file not found.\n"
            "Download OAuth 2.0 credentials from Google Cloud Console and set the path in .env",
            file=sys.stderr,
        )
        sys.exit(1)

    creds = None
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(secrets_path, SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def create_playlist(service, title: str, privacy: str = "public") -> str:
    """Create a new YouTube playlist and return its playlist ID."""
    body = {
        "snippet": {"title": title, "defaultLanguage": "fr"},
        "status": {"privacyStatus": privacy},
    }
    response = service.playlists().insert(part="snippet,status", body=body).execute()
    return response["id"]


def add_video_to_playlist(service, playlist_id: str, video_id: str) -> None:
    """Append a video to an existing YouTube playlist."""
    body = {
        "snippet": {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        }
    }
    service.playlistItems().insert(part="snippet", body=body).execute()


def upload_video(
    service,
    video_path: str,
    title: str,
    description: str,
    lat: float | None = None,
    lng: float | None = None,
    location_description: str = "",
    playlist_id: str | None = None,
) -> str:
    """Upload video to YouTube and return its URL."""
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": ["google maps", "reviews", "local business"],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": True,
        },
    }
    if lat is not None and lng is not None:
        body["recordingDetails"] = {
            "locationDescription": location_description,
            "location": {
                "latitude": lat,
                "longitude": lng,
                "altitude": 0.0,
            },
        }

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)

    try:
        request = service.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media,
        )
        response = None
        while response is None:
            _, response = request.next_chunk()
    except HttpError as e:
        print(f"Error uploading to YouTube: {e}", file=sys.stderr)
        sys.exit(1)

    video_id = response["id"]
    if playlist_id:
        try:
            add_video_to_playlist(service, playlist_id, video_id)
        except HttpError as e:
            print(f"Warning: could not add video to playlist: {e}", file=sys.stderr)
    return f"https://youtu.be/{video_id}"
