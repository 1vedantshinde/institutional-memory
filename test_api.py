#!/usr/bin/env python3
"""API endpoint verification file using FastAPI TestClient."""
import sys
import io
from fastapi.testclient import TestClient
from api.main import app

def run_api_tests():
    print("=" * 60)
    print(" STEP 11: FASTAPI ENDPOINT INTEGRATION TESTS")
    print("=" * 60)
    
    client = TestClient(app)
    
    # 1. GET /config
    print("1. Testing GET /config...")
    res = client.get("/config")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    config_data = res.json()
    original_domain_name = config_data.get("domain_name")
    print(f"-> Active Domain Name: {original_domain_name}")
    
    # 2. PUT /config (swap industries dynamically)
    print("\n2. Testing PUT /config (swapping domain context)...")
    modified_config = dict(config_data)
    modified_config["domain_name"] = "Chemical Refinery Complex V4"
    modified_config["glossary"] = [
        {"term": "FCCU", "meaning": "Fluid Catalytic Cracking Unit"}
    ]
    
    res = client.put("/config", json=modified_config)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    print(f"-> Response: {res.json()}")
    
    # Confirm reload occurred
    res = client.get("/config")
    new_domain_name = res.json().get("domain_name")
    assert new_domain_name == "Chemical Refinery Complex V4", "Reload failed to update DOMAIN!"
    print(f"-> Verified reloaded domain: {new_domain_name}")
    
    # Restore original config to leave workspace clean
    print("\n3. Restoring original domain configuration...")
    client.put("/config", json=config_data)
    
    # 4. POST /ingest (Single file upload)
    print("\n4. Testing POST /ingest upload...")
    file_payload = {"file": ("test_sop.pdf", b"Emergency FCCU procedure. Close primary valve.", "application/pdf")}
    res = client.post("/ingest", files=file_payload)
    assert res.status_code == 200, f"Ingestion failed: {res.text}"
    print(f"-> Upload response: {res.json()}")
    
    # 5. POST /query (Chatbot response)
    print("\n5. Testing POST /query...")
    res = client.post("/query?q=What is the FCCU valve procedure?")
    assert res.status_code == 200, f"Query failed: {res.text}"
    query_response = res.json()
    print(f"-> Answer Response:\n\"{query_response.get('answer')}\"")
    print(f"-> Mapped citations count: {len(query_response.get('citations', []))}")
    print(f"-> Confidence score: {query_response.get('confidence')}")
    
    print("\n" + "=" * 60)
    print(" ALL API STEP 11 TESTS COMPLETED SUCCESSFULLY! ")
    print("=" * 60)

if __name__ == "__main__":
    try:
        run_api_tests()
    except Exception as e:
        print(f"Tests failed: {e}")
        sys.exit(1)
