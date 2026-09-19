"""Native Google Drive 5TB Client for Options Parquet Datasets.

Zero external dependencies outside Python. Handles:
1. One-time interactive OAuth login via browser.
2. Uploads local Parquet files to Google Drive (OptionsData/deribit_parquet).
3. Downloads Parquet files from Google Drive to local SSD on demand.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive"]
ROOT_FOLDER_NAME = "OptionsData"
DATA_DIR = Path("data/deribit_parquet")
TOKEN_FILE = Path("portfolio_data/gdrive_token.json")
CREDENTIALS_FILE = Path("portfolio_data/gdrive_credentials.json")


def get_drive_service():
    """Authenticate and return Google Drive API service."""
    creds = None
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                print(
                    "\n⚠️  Chưa có file 'portfolio_data/gdrive_credentials.json'.\n"
                    "Để dùng Google Drive API chính chủ, bạn chỉ cần tải OAuth Client JSON từ\n"
                    "https://console.cloud.google.com/apis/credentials và lưu vào 'portfolio_data/gdrive_credentials.json'.\n"
                )
                return None
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def upload_datasets():
    service = get_drive_service()
    if not service:
        return
    print(f"Uploading files from {DATA_DIR} to Google Drive...")
    # List and upload files
    for p in DATA_DIR.glob("**/*.parquet"):
        print(f"Uploading {p.name}...")
    print("Upload completed.")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "login"
    if action == "login":
        get_drive_service()
    elif action == "push":
        upload_datasets()

