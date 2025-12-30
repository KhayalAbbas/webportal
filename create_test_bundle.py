import json
import uuid

# Create a test bundle file for validation
test_bundle = {
    "version": "1.0",
    "companies": [
        {
            "name": "Example Corp",
            "industry": "Technology",
            "employee_count": 1000,
            "revenue": 50000000,
            "headquarters": "San Francisco, CA",
            "website": "https://example.com",
            "description": "A technology company",
            "sources": [
                {
                    "url": "https://example.com",
                    "content": "Company website content",
                    "type": "website"
                }
            ]
        }
    ],
    "version_info": {
        "created_at": "2024-12-19T10:00:00Z",
        "creator": "test_system"
    }
}

with open('C:/ATS/test_bundle.json', 'w') as f:
    json.dump(test_bundle, f, indent=2)

print("Test bundle created at C:/ATS/test_bundle.json")
print(f"Bundle content: {json.dumps(test_bundle, indent=2)}")