import os
import sys
import base64
import subprocess
import requests
import truststore
truststore.inject_into_ssl()

from nacl import encoding, public

sys.path.append(r"C:\Users\ganta\OneDrive\ClaudeCode\Fidelity\Fidelity_reoccuring_orders\leveraged_tranche_engine")
try:
    from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, HEDGE_DATABASE_URL
except ImportError:
    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
    HEDGE_DATABASE_URL = os.getenv("HEDGE_DATABASE_URL", "")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
REPO_NAME = "market-data-sync"

headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
}

def encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    public_key = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")

def setup_repo():
    if not GITHUB_TOKEN:
        print("GITHUB_TOKEN environment variable not set.")
        return
    user_res = requests.get("https://api.github.com/user", headers=headers)
    user_res.raise_for_status()
    owner = user_res.json()["login"]
    print(f"Authenticated as GitHub user: {owner}")

    repo_url = f"https://api.github.com/repos/{owner}/{REPO_NAME}"
    r_check = requests.get(repo_url, headers=headers)
    if r_check.status_code == 404:
        print(f"Creating repository: {owner}/{REPO_NAME}...")
        r_create = requests.post("https://api.github.com/user/repos", headers=headers, json={
            "name": REPO_NAME,
            "private": True,
            "description": "Automated Stock & Options OHLC Data Sync with Supabase"
        })
        r_create.raise_for_status()
        print("Repository created successfully!")

if __name__ == "__main__":
    setup_repo()
