import requests

try:
    # Try to get API docs
    response = requests.get("http://127.0.0.1:8000/docs")
    print(f"Docs status: {response.status_code}")
    
    # Try openapi.json
    response2 = requests.get("http://127.0.0.1:8000/openapi.json")
    if response2.status_code == 200:
        import json
        data = response2.json()
        paths = list(data.get('paths', {}).keys())
        ui_paths = [p for p in paths if '/ui/' in p or p.startswith('/ui')]
        print(f"\nFound {len(ui_paths)} UI paths:")
        for path in sorted(ui_paths[:20]):
            print(f"  {path}")
        
        if '/ui/system-check' in paths:
            print("\n✅ /ui/system-check IS registered")
        else:
            print("\n❌ /ui/system-check NOT registered")
except Exception as e:
    print(f"Error: {e}")
