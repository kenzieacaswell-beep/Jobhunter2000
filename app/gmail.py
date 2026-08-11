import base64, json
from email.message import EmailMessage
from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import DATA_DIR, GMAIL_TOKEN_ACCOUNT
from .db import connect, get_settings, now, rows
from .keychain import get_secret, set_secret

SCOPES=["https://www.googleapis.com/auth/gmail.send"]
CLIENT=DATA_DIR/"gmail-client.json"

def connected() -> bool: return bool(get_secret(GMAIL_TOKEN_ACCOUNT))

def authorize() -> None:
    if not CLIENT.exists(): raise FileNotFoundError("Place Google OAuth desktop credentials at data/gmail-client.json")
    flow=InstalledAppFlow.from_client_secrets_file(str(CLIENT),SCOPES)
    creds=flow.run_local_server(port=0); set_secret(GMAIL_TOKEN_ACCOUNT,creds.to_json())

def send_digest(recipient: str) -> int:
    if not connected(): raise RuntimeError("Gmail is not connected")
    creds=Credentials.from_authorized_user_info(json.loads(get_secret(GMAIL_TOKEN_ACCOUNT) or "{}"),SCOPES); service=build("gmail","v1",credentials=creds)
    limit=int(get_settings()["digest_limit"])
    jobs=rows("SELECT * FROM jobs WHERE active=1 AND review_status='inbox' ORDER BY combined_score DESC LIMIT ?",(limit,))
    msg=EmailMessage(); msg["To"]=recipient; msg["From"]="me"; msg["Subject"]=f"Job Tracker: {len(jobs)} top matches"
    msg.set_content("\n\n".join([f"{j['combined_score']:.0f} — {j['title']} at {j['company_name']}\n{j['location']}\n{j['source_url']}" for j in jobs]) or "No new matches today.")
    raw=base64.urlsafe_b64encode(msg.as_bytes()).decode(); service.users().messages().send(userId="me",body={"raw":raw}).execute()
    with connect() as db: db.execute("INSERT INTO digest_runs(sent_at,job_count,status) VALUES(?,?,?)",(now(),len(jobs),"success"))
    return len(jobs)
