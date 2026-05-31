import pathlib

from flask import Blueprint, redirect, request, session, url_for, current_app

yt_oauth = Blueprint("yt_oauth", __name__, url_prefix="/youtube")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_PATH = pathlib.Path.home() / ".config" / "reviewreel" / "token.json"


@yt_oauth.get("/authorize")
def authorize():
    from google_auth_oauthlib.flow import Flow

    secrets_path = current_app.config.get("YOUTUBE_CLIENT_SECRETS", "")
    if not secrets_path:
        return "YOUTUBE_CLIENT_SECRETS not configured", 400

    flow = Flow.from_client_secrets_file(
        secrets_path,
        scopes=SCOPES,
        redirect_uri=url_for("yt_oauth.callback", _external=True),
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["oauth_state"] = state
    return redirect(auth_url)


@yt_oauth.get("/callback")
def callback():
    from google_auth_oauthlib.flow import Flow

    state = session.pop("oauth_state", None)
    secrets_path = current_app.config.get("YOUTUBE_CLIENT_SECRETS", "")
    flow = Flow.from_client_secrets_file(
        secrets_path,
        scopes=SCOPES,
        state=state,
        redirect_uri=url_for("yt_oauth.callback", _external=True),
    )
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())
    session["yt_authed"] = True
    return redirect(url_for("wizard.step5"))


def get_or_refresh_credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not TOKEN_PATH.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
        except Exception:
            return None
    return creds if (creds and creds.valid) else None
