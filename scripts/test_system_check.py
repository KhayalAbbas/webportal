import requests

try:
    response = requests.get("http://127.0.0.1:8000/ui/system-check", allow_redirects=False)
    print(f"Status: {response.status_code}")
    if response.status_code == 404:
        print("Content:", response.text[:200])
    elif response.status_code == 307:
        print("Redirect to:", response.headers.get('Location'))
    else:
        print("Success! Page loads.")
except Exception as e:
    print(f"Error: {e}")
