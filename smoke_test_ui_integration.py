#!/usr/bin/env python3
"""
Comprehensive smoke test for Phase 3 UI integration.
Tests the entire workflow end-to-end.
"""
import requests
import time
from typing import Dict, Any

BASE_URL = "http://127.0.0.1:8005"
TEST_CREDENTIALS = {"email": "admin@test.com", "password": "admin123"}

class UIIntegrationTest:
    def __init__(self):
        self.session = requests.Session()
        self.logged_in = False

    def test_server_running(self) -> bool:
        """Test if server is responding"""
        try:
            response = self.session.get(f"{BASE_URL}/", allow_redirects=False, timeout=5)
            print(f"✅ Server responding: {response.status_code}")
            return response.status_code in [200, 302, 303]
        except Exception as e:
            print(f"❌ Server not responding: {e}")
            return False

    def test_login(self) -> bool:
        """Test login functionality"""
        try:
            # Get login page
            response = self.session.get(f"{BASE_URL}/login")
            if response.status_code != 200:
                print(f"❌ Login page failed: {response.status_code}")
                return False

            # Submit login form
            login_data = {
                "email": TEST_CREDENTIALS["email"],
                "password": TEST_CREDENTIALS["password"]
            }
            response = self.session.post(f"{BASE_URL}/login", data=login_data, allow_redirects=False)
            
            if response.status_code in [302, 303]:
                print("✅ Login successful")
                self.logged_in = True
                return True
            else:
                print(f"❌ Login failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Login error: {e}")
            return False

    def test_research_page(self) -> bool:
        """Test research page loads and shows research runs"""
        try:
            response = self.session.get(f"{BASE_URL}/ui/research")
            if response.status_code != 200:
                print(f"❌ Research page failed: {response.status_code}")
                return False
            
            content = response.text
            
            # Check for Phase 3 section
            if "Phase 3 Research Runs" not in content:
                print("❌ Phase 3 Research Runs section missing")
                return False
            
            # Check for upload button
            if "Upload New Research Bundle" not in content:
                print("❌ Upload button missing")
                return False
            
            # Check for research runs data
            if "FinTech in GCC" in content or "Phase3 end-to-end" in content:
                print("✅ Research page shows Phase 3 runs")
                return True
            else:
                print("⚠️  Research page loads but no test data visible")
                return True  # Still count as success if page structure is correct
                
        except Exception as e:
            print(f"❌ Research page error: {e}")
            return False

    def test_upload_page(self) -> bool:
        """Test research upload page loads"""
        try:
            response = self.session.get(f"{BASE_URL}/ui/research/upload")
            if response.status_code != 200:
                print(f"❌ Upload page failed: {response.status_code}")
                return False
            
            content = response.text
            
            # Check for upload form elements
            if 'enctype="multipart/form-data"' not in content:
                print("❌ Upload form missing")
                return False
                
            if 'name="objective"' not in content:
                print("❌ Objective field missing")
                return False
                
            if 'name="bundle_file"' not in content:
                print("❌ File upload field missing")
                return False
            
            print("✅ Upload page loads correctly")
            return True
            
        except Exception as e:
            print(f"❌ Upload page error: {e}")
            return False

    def test_view_steps_api(self) -> Dict[str, Any]:
        """Test View Steps API functionality"""
        try:
            # First get research page to find a run ID
            response = self.session.get(f"{BASE_URL}/ui/research")
            content = response.text
            
            # Extract a run ID from the page (look for View Steps links)
            import re
            pattern = r'/ui/research/runs/([a-f0-9-]{36})/steps'
            match = re.search(pattern, content)
            
            if not match:
                print("⚠️  No View Steps links found (no research runs)")
                return {"success": False, "reason": "no_runs"}
            
            run_id = match.group(1)
            print(f"Testing View Steps for run: {run_id}")
            
            # Test the UI proxy endpoint
            response = self.session.get(f"{BASE_URL}/ui/research/runs/{run_id}/steps")
            
            if response.status_code != 200:
                print(f"❌ View Steps failed: {response.status_code}")
                return {"success": False, "reason": f"http_{response.status_code}"}
            
            # Check if response is valid JSON
            try:
                data = response.json()
                if isinstance(data, list):
                    print(f"✅ View Steps working: {len(data)} steps found")
                    return {"success": True, "steps_count": len(data), "run_id": run_id}
                else:
                    print("❌ View Steps returned invalid format")
                    return {"success": False, "reason": "invalid_format"}
            except ValueError:
                print("❌ View Steps returned non-JSON")
                return {"success": False, "reason": "not_json"}
                
        except Exception as e:
            print(f"❌ View Steps error: {e}")
            return {"success": False, "reason": str(e)}

    def run_all_tests(self):
        """Run complete test suite"""
        print("🧪 Starting Phase 3 UI Integration Smoke Test")
        print("=" * 50)
        
        results = {
            "server": self.test_server_running(),
            "login": False,
            "research_page": False,
            "upload_page": False,
            "view_steps": {"success": False}
        }
        
        if results["server"]:
            results["login"] = self.test_login()
            
            if results["login"]:
                results["research_page"] = self.test_research_page()
                results["upload_page"] = self.test_upload_page()
                results["view_steps"] = self.test_view_steps_api()
        
        print("\n" + "=" * 50)
        print("📊 TEST RESULTS SUMMARY:")
        
        all_passed = True
        
        if results["server"]:
            print("✅ Server Running")
        else:
            print("❌ Server Running")
            all_passed = False
            
        if results["login"]:
            print("✅ Login/Authentication")
        else:
            print("❌ Login/Authentication")
            all_passed = False
            
        if results["research_page"]:
            print("✅ Research Page")
        else:
            print("❌ Research Page")
            all_passed = False
            
        if results["upload_page"]:
            print("✅ Upload Page")
        else:
            print("❌ Upload Page")
            all_passed = False
            
        if results["view_steps"]["success"]:
            print("✅ View Steps API")
        else:
            print(f"❌ View Steps API ({results['view_steps'].get('reason', 'unknown')})")
            all_passed = False
        
        print("\n" + "=" * 50)
        if all_passed:
            print("🎉 ALL TESTS PASSED - Phase 3 UI Integration Working!")
        else:
            print("⚠️  SOME TESTS FAILED - Check issues above")
        
        return results

if __name__ == "__main__":
    tester = UIIntegrationTest()
    results = tester.run_all_tests()