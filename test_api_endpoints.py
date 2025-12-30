import asyncio
import json
import aiohttp

async def test_bundle_upload():
    # Test non-existent endpoint first
    async with aiohttp.ClientSession() as session:
        # Test invalid endpoint
        async with session.post(
            "http://localhost:8005/api/companies/1/research-run",
            json={"bundle": "test"}
        ) as resp:
            print(f"Status: {resp.status}")
            text = await resp.text()
            print(f"Response: {text}")
            
        # Try direct upload to research_run_service using correct endpoint structure
        # Let's check if there's a working endpoint by looking at the service directly
        with open('C:/ATS/test_bundle.json', 'r') as f:
            bundle_data = json.load(f)
        
        # Try multiple possible endpoints
        endpoints = [
            "/api/research-runs",
            "/api/company-research/runs",
            "/research-runs", 
            "/api/bundles"
        ]
        
        for endpoint in endpoints:
            try:
                async with session.post(
                    f"http://localhost:8005{endpoint}",
                    json=bundle_data
                ) as resp:
                    print(f"Endpoint {endpoint}: Status {resp.status}")
                    if resp.status != 404:
                        text = await resp.text()
                        print(f"Response: {text}")
            except Exception as e:
                print(f"Error testing {endpoint}: {e}")

if __name__ == "__main__":
    asyncio.run(test_bundle_upload())