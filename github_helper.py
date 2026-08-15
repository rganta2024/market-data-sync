import os
import requests
import truststore
truststore.inject_into_ssl()

token = os.getenv("GITHUB_TOKEN", "")
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
}

def get_user_info():
    if not token:
        print("GITHUB_TOKEN not set.")
        return None
    r = requests.get("https://api.github.com/user", headers=headers)
    if r.status_code == 200:
        data = r.json()
        print("GitHub Username:", data.get("login"))
        return data.get("login")
    return None

if __name__ == "__main__":
    get_user_info()
