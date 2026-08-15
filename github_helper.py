import truststore
truststore.inject_into_ssl()
import requests

token = "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"
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
}

def get_user_info():
    r = requests.get("https://api.github.com/user", headers=headers)
    if r.status_code == 200:
        data = r.json()
        print("GitHub Username:", data.get("login"))
        print("Name:", data.get("name"))
        return data.get("login")
    else:
        print("Error fetching user:", r.status_code, r.text)
        return None

def list_repos():
    r = requests.get("https://api.github.com/user/repos?sort=updated&per_page=15", headers=headers)
    if r.status_code == 200:
        print("\nRecent Repositories:")
        for repo in r.json():
            print(f" - {repo.get('name')} (Private: {repo.get('private')}) -> {repo.get('html_url')}")
    else:
        print("Error listing repos:", r.status_code, r.text)

if __name__ == "__main__":
    get_user_info()
    list_repos()
