import os
import sys
import base64
import subprocess
import requests
import truststore
truststore.inject_into_ssl()

from nacl import encoding, public

sys.path.append(r"C:\Users\ganta\OneDrive\ClaudeCode\Fidelity\Fidelity_reoccuring_orders\leveraged_tranche_engine")
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, HEDGE_DATABASE_URL

GITHUB_TOKEN = "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"
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
    # 1. Get user
    user_res = requests.get("https://api.github.com/user", headers=headers)
    user_res.raise_for_status()
    owner = user_res.json()["login"]
    print(f"Authenticated as GitHub user: {owner}")

    # 2. Check or create repo
    repo_url = f"https://api.github.com/repos/{owner}/{REPO_NAME}"
    r_check = requests.get(repo_url, headers=headers)
    if r_check.status_code == 404:
        print(f"Creating private repository: {owner}/{REPO_NAME}...")
        r_create = requests.post("https://api.github.com/user/repos", headers=headers, json={
            "name": REPO_NAME,
            "private": True,
            "description": "Automated Stock & Options OHLC Data Sync with Supabase"
        })
        r_create.raise_for_status()
        print("Repository created successfully!")
    else:
        print(f"Repository {owner}/{REPO_NAME} already exists.")

    # 3. Get Public Key for Secrets
    pk_url = f"https://api.github.com/repos/{owner}/{REPO_NAME}/actions/secrets/public-key"
    pk_res = requests.get(pk_url, headers=headers)
    pk_res.raise_for_status()
    pk_data = pk_res.json()
    key_id = pk_data["key_id"]
    public_key = pk_data["key"]

    # 4. Upload Secrets
    secrets_to_upload = {
        "ALPACA_API_KEY": ALPACA_API_KEY,
        "ALPACA_SECRET_KEY": ALPACA_SECRET_KEY,
        "HEDGE_DATABASE_URL": HEDGE_DATABASE_URL
    }

    for s_name, s_val in secrets_to_upload.items():
        if not s_val:
            print(f"Warning: Secret {s_name} is empty, skipping.")
            continue
        enc_val = encrypt_secret(public_key, s_val)
        put_url = f"https://api.github.com/repos/{owner}/{REPO_NAME}/actions/secrets/{s_name}"
        put_res = requests.put(put_url, headers=headers, json={
            "encrypted_value": enc_val,
            "key_id": key_id
        })
        if put_res.status_code in [201, 204]:
            print(f" - Secret '{s_name}' uploaded successfully.")
        else:
            print(f" - Failed to upload secret '{s_name}': {put_res.status_code} {put_res.text}")

    # 5. Push Code using Git
    project_dir = os.path.dirname(__file__)
    print(f"\nPushing repository code to https://github.com/{owner}/{REPO_NAME}...")
    
    commands = [
        ["git", "init"],
        ["git", "config", "user.name", "rganta2024"],
        ["git", "config", "user.email", "raghu.ganta@gmail.com"],
        ["git", "add", "."],
        ["git", "commit", "-m", "Initial commit: Stock & Options Supabase Sync Pipeline"],
        ["git", "branch", "-M", "main"],
        ["git", "remote", "remove", "origin"],
        ["git", "remote", "add", "origin", f"https://{owner}:{GITHUB_TOKEN}@github.com/{owner}/{REPO_NAME}.git"],
        ["git", "push", "-u", "origin", "main", "--force"]
    ]

    for cmd in commands:
        try:
            res = subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True)
            if res.returncode != 0 and "remove" not in cmd[1]:
                print(f"Command {' '.join(cmd[:2])} warning: {res.stderr.strip() or res.stdout.strip()}")
        except Exception as e:
            print(f"Git error on {' '.join(cmd)}: {e}")

    print("\nGit push complete! Repository is live at: https://github.com/" + f"{owner}/{REPO_NAME}")
    return owner, REPO_NAME

if __name__ == "__main__":
    setup_repo()
