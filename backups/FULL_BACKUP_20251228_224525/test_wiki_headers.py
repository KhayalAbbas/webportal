import httpx
import asyncio
import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.server]

async def test_wikipedia():
    headers = {
        'User-Agent': 'ATS-Research-Bot/1.0 (Educational; Python/httpx)',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive'
    }
    
    url = 'https://en.wikipedia.org/wiki/List_of_banks_in_Moldova'
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            print(f"Status: {response.status_code}")
            print(f"Content length: {len(response.text)}")
            
            if response.status_code == 200:
                print("✅ Successfully fetched Wikipedia!")
                # Check if we got actual content
                if '<table class="wikitable">' in response.text:
                    print("✅ Found wikitable structure")
                return True
            else:
                print(f"❌ Failed with status: {response.status_code}")
                return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_wikipedia())
    print(f"\nTest result: {'PASS' if result else 'FAIL'}")
