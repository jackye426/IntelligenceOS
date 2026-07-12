"""Generate a Gmail OAuth refresh token from client_secret.json.

Run from the repo root:
  python relationship-desk-mcp/generate_gmail_refresh_token.py
"""

from __future__ import annotations

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    client_secret = repo_root / "client_secret.json"
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(
        host="localhost",
        port=8080,
        open_browser=False,
        prompt="consent",
        authorization_prompt_message="\nOpen this URL and approve Gmail access:\n{url}\n",
        success_message="Gmail authorization complete. You can close this tab.",
    )
    print("\nRELATIONSHIP_GMAIL_REFRESH_TOKEN=" + (creds.refresh_token or ""), flush=True)


if __name__ == "__main__":
    main()
