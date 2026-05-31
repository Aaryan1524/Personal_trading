# Run once each morning before market open
import json
import webbrowser
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv
from kiteconnect import KiteConnect
import os

TOKEN_PATH = Path(__file__).resolve().parent / "token.json"


def main():
    load_dotenv()
    api_key = os.environ["KITE_API_KEY"]
    api_secret = os.environ["KITE_API_SECRET"]

    kite = KiteConnect(api_key=api_key)
    login_url = kite.login_url()

    print("Opening Kite login URL in your browser...")
    webbrowser.open(login_url)

    print()
    print("After logging in, Kite will redirect you to a URL that looks like:")
    print("  https://your-redirect.example/?request_token=XXXX&action=login&status=success")
    print("Copy that full redirect URL and paste it below.")
    print()

    redirect_url = input("Redirect URL: ").strip()
    query = parse_qs(urlparse(redirect_url).query)
    request_tokens = query.get("request_token")
    if not request_tokens:
        raise SystemExit("Could not find request_token in the URL you pasted.")
    request_token = request_tokens[0]

    session = kite.generate_session(request_token, api_secret=api_secret)
    access_token = session["access_token"]

    TOKEN_PATH.write_text(json.dumps({"access_token": access_token, "api_key": api_key}))
    print(f"Success. Access token saved to {TOKEN_PATH}")


if __name__ == "__main__":
    main()
