import httpx
import asyncio
import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.server]

async def test_wikipedia_api():
    """Test Wikipedia REST API access"""
    
    # Test URL
    wiki_url = 'https://en.wikipedia.org/wiki/List_of_banks_in_Moldova'
    page_title = wiki_url.split('/wiki/')[-1]
    
    # Wikipedia REST API endpoint
    api_url = f"https://en.wikipedia.org/api/rest_v1/page/html/{page_title}"
    
    print(f"Original URL: {wiki_url}")
    print(f"Page title: {page_title}")
    print(f"API URL: {api_url}")
    print()
    
    headers = {
        'User-Agent': 'ATS-Research-Bot/1.0 (Educational purposes; Python/httpx)',
        'Api-User-Agent': 'ATS-Research-Bot/1.0 (Educational purposes)'
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(api_url, headers=headers)
            print(f"Status: {response.status_code}")
            print(f"Content length: {len(response.text)}")
            
            if response.status_code == 200:
                print("✅ Successfully fetched via Wikipedia API!")
                
                # Check for table structure
                if '<table class="wikitable">' in response.text or 'wikitable' in response.text:
                    print("✅ Found wikitable in content")
                else:
                    print("⚠️ No wikitable found")
                
                # Show first 500 chars
                print(f"\nFirst 500 chars of content:")
                print(response.text[:500])
                
                return True
            else:
                print(f"❌ Failed with status: {response.status_code}")
                print(f"Response: {response.text[:200]}")
                return False
                
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_wikipedia_api())
    print(f"\n{'='*50}")
    print(f"Test result: {'PASS ✅' if result else 'FAIL ❌'}")
