"""
Fetch and analyze the gfmag page structure.
"""
import httpx
from bs4 import BeautifulSoup

url = "https://gfmag.com/award/worlds-safest-banks-2025-islamic-banks-in-gcc/"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

response = httpx.get(url, headers=headers, follow_redirects=True, timeout=30)
print(f"Status: {response.status_code}")
print(f"Content length: {len(response.text)}")

soup = BeautifulSoup(response.text, 'html.parser')

# Remove unwanted elements
for elem in soup.select('script, style, nav, footer, header, aside, button'):
    elem.decompose()

print("\n=== TABLES ===")
tables = soup.find_all('table')
print(f"Found {len(tables)} tables")
for i, table in enumerate(tables, 1):
    print(f"\nTable {i}:")
    print(f"Classes: {table.get('class', [])}")
    rows = table.find_all('tr')
    print(f"Rows: {len(rows)}")
    if rows:
        first_row = rows[0]
        cells = first_row.find_all(['th', 'td'])
        print(f"First row cells: {[cell.get_text(strip=True)[:50] for cell in cells[:5]]}")

print("\n\n=== LISTS ===")
lists = soup.find_all(['ul', 'ol'])
print(f"Found {len(lists)} lists")
for i, lst in enumerate(lists[:10], 1):
    print(f"\nList {i}:")
    print(f"Classes: {lst.get('class', [])}")
    print(f"ID: {lst.get('id', 'none')}")
    items = lst.find_all('li', recursive=False)
    print(f"Items: {len(items)}")
    if items:
        print(f"First 3 items: {[item.get_text(strip=True)[:50] for item in items[:3]]}")
