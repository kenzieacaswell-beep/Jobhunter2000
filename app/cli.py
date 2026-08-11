import argparse, asyncio, json
from .db import init_db
from .ingestion import refresh_all
from .keychain import set_secret
from .config import DEEPSEEK_KEY_ACCOUNT
from .seeds import seed_companies
from .gmail import authorize as gmail_authorize, send_digest
from .db import get_settings

def main():
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("init"); sub.add_parser("refresh"); sub.add_parser("seed-companies"); sub.add_parser("gmail-auth"); digest=sub.add_parser("send-digest"); digest.add_argument("recipient",nargs="?"); key=sub.add_parser("set-deepseek-key"); key.add_argument("key",nargs="?")
    args=parser.parse_args(); init_db()
    if args.command=="refresh": print(json.dumps(asyncio.run(refresh_all()),indent=2))
    elif args.command=="gmail-auth": gmail_authorize(); print("Gmail OAuth token stored in macOS Keychain.")
    elif args.command=="send-digest": print(f"Sent {send_digest(args.recipient or get_settings().get('digest_recipient',''))} jobs.")
    elif args.command=="set-deepseek-key":
        import getpass
        set_secret(DEEPSEEK_KEY_ACCOUNT,args.key or getpass.getpass("DeepSeek API key: ")); print("Stored in macOS Keychain.")
    elif args.command=="seed-companies": print(f"Seeded {seed_companies()} editable company sources (disabled for review).")
    else: print("Database initialized.")
if __name__=="__main__": main()
