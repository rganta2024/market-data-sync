import os
import time
import requests
import truststore
truststore.inject_into_ssl()

token = os.getenv("GITHUB_TOKEN", "")
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
}

owner = "rganta2024"
repo = "market-data-sync"
workflow_file = "daily_market_sync.yml"

def trigger_and_monitor():
    if not token:
        print("GITHUB_TOKEN not set.")
        return
    print(f"Triggering GitHub Action '{workflow_file}' on '{owner}/{repo}'...")
    dispatch_url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow_file}/dispatches"
    r = requests.post(dispatch_url, headers=headers, json={"ref": "main"})
    print("Dispatch HTTP Status:", r.status_code)
    
    if r.status_code != 204:
        print("Dispatch failed:", r.text)
        return

    print("SUCCESS: Dispatch signal accepted!")

if __name__ == "__main__":
    trigger_and_monitor()
