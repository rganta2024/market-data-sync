import time
import requests
import truststore
truststore.inject_into_ssl()

token = "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"
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
}

owner = "rganta2024"
repo = "market-data-sync"
workflow_file = "daily_market_sync.yml"

def trigger_and_monitor():
    print(f"Triggering GitHub Action '{workflow_file}' on '{owner}/{repo}'...")
    dispatch_url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow_file}/dispatches"
    r = requests.post(dispatch_url, headers=headers, json={"ref": "main"})
    print("Dispatch HTTP Status:", r.status_code)
    
    if r.status_code != 204:
        print("Dispatch failed:", r.text)
        return

    print("SUCCESS: Dispatch signal accepted! Polling workflow execution...")
    time.sleep(5)

    runs_url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
    
    for _ in range(15):
        r_runs = requests.get(runs_url, headers=headers)
        if r_runs.status_code == 200:
            runs = r_runs.json().get("workflow_runs", [])
            if runs:
                latest = runs[0]
                run_id = latest.get("id")
                status = latest.get("status")
                conclusion = latest.get("conclusion")
                html_url = latest.get("html_url")
                print(f"Run #{run_id}: status={status} | conclusion={conclusion} | url={html_url}")
                
                if status == "completed":
                    print(f"\nWORKFLOW COMPLETED WITH CONCLUSION: {conclusion.upper()}!")
                    return
        time.sleep(5)

if __name__ == "__main__":
    trigger_and_monitor()
