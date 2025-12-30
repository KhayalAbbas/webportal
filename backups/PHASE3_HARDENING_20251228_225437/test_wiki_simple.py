import httpx
import asyncio
import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.server]

async def test_simple_request():
    """Test a very simple Wikipedia request to see if we're rate-limited"""
    
    url = "https://en.wikipedia.org/w/api.php?action=query&titles=Main_Page&format=json"
    
    headers = {
        'User-Agent': 'ATS-Research-Tool/1.0 (Educational; non-commercial)',
    }
    
    print("Testing simple Wikipedia API query...")
    print(f"URL: {url}\n")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Add a small delay to be polite
            await asyncio.sleep(1)
            
            response = await client.get(url, headers=headers)
            print(f"Status: {response.status_code}")
            print(f"Response length: {len(response.text)}")
            
            if response.status_code == 200:
                print("✅ Wikipedia API is accessible!")
                print(f"Response preview: {response.text[:200]}")
                return True
            else:
                print(f"❌ Got {response.status_code}")
                print(f"Response: {response.text}")
                return False
                
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_simple_request())
    print(f"\nTest: {'PASS' if result else 'FAIL'}")
