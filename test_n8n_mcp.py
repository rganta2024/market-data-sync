import truststore
truststore.inject_into_ssl()
import requests
import json

url = "https://rganta.app.n8n.cloud/mcp-server/http"
token = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4ZjBmMjk3Zi1mN2E5LTQyYWUtYjgyNy05OGQxOWU4NTM0YWEiLCJpc3MiOiJuOG4iLCJhdWQiOiJtY3Atc2VydmVyLWFwaSIsImp0aSI6IjUxYmFhMTRhLWY1OTEtNDBiOC1iY2FlLTZmY2I3MDBiY2E2NiIsImlhdCI6MTc4NjgwNTYzMX0.RIeb6V7o3UJKeDbLwunmXEVQ8xevpn4NHpNZ8yoWj4g"
headers = {
    "Authorization": token,
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream"
}

def main():
    print("Testing connection to n8n MCP Server at:", url)
    
    # 1. Initialize
    init_res = requests.post(url, headers=headers, json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "Antigravity", "version": "1.0"}
        }
    }, timeout=10)
    print("Initialize Status:", init_res.status_code)
    
    # 2. List tools
    tools_res = requests.post(url, headers=headers, json={
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    }, timeout=10)
    print("Tools/List Status:", tools_res.status_code)
    
    # 3. Search Workflows
    wf_res = requests.post(url, headers=headers, json={
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "search_workflows",
            "arguments": {}
        }
    }, timeout=10)
    print("Search Workflows Status:", wf_res.status_code)
    
    for line in wf_res.text.splitlines():
        if line.startswith("data:"):
            data = json.loads(line[5:].strip())
            content = data.get("result", {}).get("content", [])
            for c in content:
                print("\nWorkflows in n8n Cloud Instance:")
                print(c.get("text", "")[:1000])

if __name__ == "__main__":
    main()
