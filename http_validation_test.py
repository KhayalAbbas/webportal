import httpx
import asyncio
import json

async def test_http_validation():
    invalid_bundle = {
        "company_name": "TestCorp",
        "sources": [{
            "name": "test.pdf",
            "sha256": "invalid_sha",
            "content": "Test content"
        }],
        "query": "What is TestCorp's revenue?"
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "http://localhost:8005/api/research-runs/upload",
                json=invalid_bundle
            )
            print(f"POST http://localhost:8005/api/research-runs/upload")
            print(f"Status: {response.status_code}")
            print(f"Headers: {dict(response.headers)}")
            print(f"Body: {response.text}")
    except Exception as e:
        print(f"HTTP Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_http_validation())