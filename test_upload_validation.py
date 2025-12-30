import httpx
import json
import asyncio

async def test_upload_validation():
    """Test upload-time validation via HTTP API"""
    print("=== UPLOAD VALIDATION TEST ===")
    
    # Start with an invalid bundle (bad SHA256)
    invalid_bundle = {
        "company_name": "TestCorp",
        "sources": [{
            "name": "test.pdf",
            "sha256": "invalid_sha",  # Invalid - too short
            "content": "Test content"
        }],
        "query": "What is TestCorp's revenue?"
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Test invalid bundle
            print("Testing invalid bundle upload...")
            response = await client.post(
                "http://localhost:8005/research-upload",
                json=invalid_bundle,
                headers={"Content-Type": "application/json"}
            )
            
            print(f"Status Code: {response.status_code}")
            print(f"Response Headers: {dict(response.headers)}")
            print(f"Response Body: {response.text}")
            
            # Test valid bundle
            valid_bundle = {
                "company_name": "ValidCorp", 
                "sources": [{
                    "name": "annual_report.pdf",
                    "sha256": "a" * 64,  # Valid 64-char hex
                    "content": "ValidCorp annual revenue is $100M. Founded in 2020."
                }],
                "query": "What is ValidCorp's annual revenue?"
            }
            
            print("\nTesting valid bundle upload...")
            response = await client.post(
                "http://localhost:8005/research-upload", 
                json=valid_bundle,
                headers={"Content-Type": "application/json"}
            )
            
            print(f"Status Code: {response.status_code}")
            print(f"Response Headers: {dict(response.headers)}")
            print(f"Response Body: {response.text}")
            
    except Exception as e:
        print(f"HTTP test failed: {e}")
        print("Trying direct service validation...")
        
        # Test via direct service call
        from app.services.research_run_service import ResearchRunService
        from app.db.session import async_session_maker
        
        async with async_session_maker() as session:
            service = ResearchRunService(session)
            
            try:
                result = await service.accept_bundle(
                    "22222222-2222-2222-2222-222222222222",
                    invalid_bundle,
                    accept_only=True
                )
                print(f"❌ Invalid bundle should have been rejected: {result}")
            except Exception as validation_error:
                print(f"✅ Invalid bundle correctly rejected: {validation_error}")
                
            try:
                result = await service.accept_bundle(
                    "22222222-2222-2222-2222-222222222222",
                    valid_bundle,
                    accept_only=True
                )
                print(f"✅ Valid bundle accepted: {result}")
            except Exception as e:
                print(f"❌ Valid bundle rejected: {e}")

if __name__ == "__main__":
    asyncio.run(test_upload_validation())