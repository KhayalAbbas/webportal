import httpx
import asyncio
import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.server]

async def test_wikipedia_action_api():
    """Test Wikipedia Action API (parse action) - more permissive"""
    
    # Test URL
    wiki_url = 'https://en.wikipedia.org/wiki/List_of_banks_in_Moldova'
    page_title = wiki_url.split('/wiki/')[-1]
    
    # Wikipedia Action API endpoint
    api_url = "https://en.wikipedia.org/w/api.php"
    params = {
        'action': 'parse',
        'page': page_title,
        'format': 'json',
        'prop': 'text',
        'formatversion': '2'
    }
    
    print(f"Original URL: {wiki_url}")
    print(f"Page title: {page_title}")
    print(f"API URL: {api_url}")
    print(f"Params: {params}")
    print()
    
    headers = {
        'User-Agent': 'ATS-Research-Bot/1.0 (Educational/Research; Python/httpx; non-commercial)',
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(api_url, params=params, headers=headers)
            print(f"Status: {response.status_code}")
            print(f"Content length: {len(response.text)}")
            
            if response.status_code == 200:
                data = response.json()
                
                if 'parse' in data and 'text' in data['parse']:
                    html_content = data['parse']['text']
                    print(f"✅ Successfully fetched via Wikipedia Action API!")
                    print(f"HTML content length: {len(html_content)}")
                    
                    # Check for table structure
                    if 'wikitable' in html_content:
                        print("✅ Found wikitable in content")
                    else:
                        print("⚠️ No wikitable found")
                    
                    # Show first 500 chars
                    print(f"\nFirst 500 chars of HTML:")
                    print(html_content[:500])
                    
                    return True
                else:
                    print(f"❌ Unexpected API response format: {data}")
                    return False
            else:
                print(f"❌ Failed with status: {response.status_code}")
                print(f"Response: {response.text[:200]}")
                return False
                
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_wikipedia_action_api())
    print(f"\n{'='*50}")
    print(f"Test result: {'PASS ✅' if result else 'FAIL ❌'}")
