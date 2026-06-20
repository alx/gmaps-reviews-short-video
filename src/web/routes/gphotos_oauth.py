from pathlib import Path

import httpx
from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

gp_oauth = Blueprint("gp_oauth", __name__, url_prefix="/gphotos")

SCOPES = ["https://www.googleapis.com/auth/photoslibrary.readonly"]
_PHOTOS_BASE = "https://photoslibrary.googleapis.com/v1"


def _token_path(session_dir: str) -> Path:
    return Path(session_dir) / "gphotos_token.json"


def _get_session_dir() -> str | None:
    """Resolve session_dir from the fetch task stored in the Flask session."""
    from ..tasks import store

    task_id = session.get("fetch_task_id")
    if not task_id:
        return None
    task = store.get(task_id)
    if not task or not task.result:
        return None
    return task.result.get("session_dir")


def get_or_refresh_gp_credentials(session_dir: str):
    """Return valid Credentials for this session, refreshing if needed. Returns None if not authed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_path = _token_path(session_dir)
    if not token_path.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            workspace_dir = Path(current_app.config["WORKSPACE_DIR"])
            base_dir = (workspace_dir / "sessions").resolve()
            token_path_resolved = token_path.resolve()
            try:
                token_path_resolved.relative_to(base_dir)
            except ValueError:
                raise Exception("Invalid file path")
            token_path_resolved.write_text(creds.to_json())
        except Exception:
            return None
    return creds if (creds and creds.valid) else None


def _authed_get(session_dir: str, url: str, **params):
    """Make an authenticated GET to the Photos API. Returns parsed JSON or raises."""
    creds = get_or_refresh_gp_credentials(session_dir)
    if not creds:
        raise PermissionError("not authenticated")
    headers = {"Authorization": f"Bearer {creds.token}"}
    resp = httpx.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _authed_post(session_dir: str, url: str, body: dict):
    """Make an authenticated POST to the Photos API. Returns parsed JSON or raises."""
    creds = get_or_refresh_gp_credentials(session_dir)
    if not creds:
        raise PermissionError("not authenticated")
    headers = {"Authorization": f"Bearer {creds.token}"}
    resp = httpx.post(url, headers=headers, json=body, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# OAuth routes
# ---------------------------------------------------------------------------

@gp_oauth.get("/authorize")
def authorize():
    from google_auth_oauthlib.flow import Flow

    secrets_path = current_app.config.get("GPHOTOS_CLIENT_SECRETS", "")
    if not secrets_path or not Path(secrets_path).exists():
        return (
            "GPHOTOS_CLIENT_SECRETS not configured or file not found. "
            "See .env.example for setup instructions.",
            400,
        )

    flow = Flow.from_client_secrets_file(
        secrets_path,
        scopes=SCOPES,
        redirect_uri=url_for("gp_oauth.callback", _external=True),
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["gp_oauth_state"] = state
    session["gp_next"] = request.referrer or url_for("wizard.step1")
    return redirect(auth_url)


@gp_oauth.get("/callback")
def callback():
    from google_auth_oauthlib.flow import Flow

    state = session.pop("gp_oauth_state", None)
    secrets_path = current_app.config.get("GPHOTOS_CLIENT_SECRETS", "")
    flow = Flow.from_client_secrets_file(
        secrets_path,
        scopes=SCOPES,
        state=state,
        redirect_uri=url_for("gp_oauth.callback", _external=True),
    )
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials

    session_dir = _get_session_dir()
    if session_dir:
        token_path = _token_path(session_dir)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())

    session["gp_authed"] = True
    next_url = session.pop("gp_next", url_for("wizard.step1"))
    return redirect(next_url)


# ---------------------------------------------------------------------------
# HTMX browse routes
# ---------------------------------------------------------------------------

@gp_oauth.get("/albums")
def albums():
    session_dir = _get_session_dir()
    if not session_dir or not get_or_refresh_gp_credentials(session_dir):
        return render_template("fragments/gphotos_not_connected.html")

    page_token = request.args.get("page_token", "")
    params = {"pageSize": 50}
    if page_token:
        params["pageToken"] = page_token

    try:
        data = _authed_get(session_dir, f"{_PHOTOS_BASE}/albums", **params)
    except Exception as exc:
        return f'<p class="muted">Error loading albums: {exc}</p>', 200

    return render_template(
        "fragments/gphotos_albums.html",
        albums=data.get("albums", []),
        next_page_token=data.get("nextPageToken", ""),
    )


@gp_oauth.get("/media")
def media():
    session_dir = _get_session_dir()
    if not session_dir or not get_or_refresh_gp_credentials(session_dir):
        return render_template("fragments/gphotos_not_connected.html")

    album_id = request.args.get("album_id", "")
    page_token = request.args.get("page_token", "")
    body: dict = {"pageSize": 50}
    if album_id:
        body["albumId"] = album_id
    if page_token:
        body["pageToken"] = page_token

    try:
        data = _authed_post(session_dir, f"{_PHOTOS_BASE}/mediaItems:search", body)
    except Exception as exc:
        return f'<p class="muted">Error loading photos: {exc}</p>', 200

    # Keep only photo items (skip videos)
    items = [
        item for item in data.get("mediaItems", [])
        if item.get("mediaMetadata", {}).get("photo") is not None
    ]

    return render_template(
        "fragments/gphotos_media.html",
        items=items,
        album_id=album_id,
        next_page_token=data.get("nextPageToken", ""),
    )
