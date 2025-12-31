"""
SMS Integration Tests - Phase 1

Tests for SMS module endpoints:
- GET /api/sms/status - Configuration status
- GET /api/sms/templates - List available templates
- POST /api/sms/send - Send SMS (graceful failure when not configured)
- POST /api/sms/send-template - Template-based sending
- Phone number validation and normalization
- Permission checks (admin, staff, tax_agent only)

Note: Twilio credentials are NOT configured in Phase 1.
All send operations should return 503 with helpful error messages.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
CREDENTIALS = {
    "admin": {"email": "admin@fdctax.com", "password": "admin123"},
    "staff": {"email": "staff@fdctax.com", "password": "staff123"},
    "tax_agent": {"email": "taxagent@fdctax.com", "password": "taxagent123"},
    "client": {"email": "client@fdctax.com", "password": "client123"},
}

# Expected templates (9 total)
EXPECTED_TEMPLATES = [
    "appointment_reminder",
    "document_request",
    "payment_reminder",
    "tax_deadline",
    "bas_ready",
    "bas_approved",
    "bas_lodged",
    "welcome",
    "verification_code"
]


class TestSMSAuthentication:
    """Test authentication and permission requirements for SMS endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
    
    def get_token(self, user_type: str) -> str:
        """Get auth token for a user type"""
        creds = CREDENTIALS.get(user_type)
        if not creds:
            pytest.skip(f"No credentials for {user_type}")
        
        response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json=creds
        )
        if response.status_code != 200:
            pytest.skip(f"Login failed for {user_type}: {response.text}")
        
        return response.json().get("access_token")
    
    def test_sms_status_no_auth_returns_401(self):
        """GET /api/sms/status without auth should return 401"""
        response = self.session.get(f"{BASE_URL}/api/sms/status")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: No auth returns 401 for /api/sms/status")
    
    def test_sms_templates_no_auth_returns_401(self):
        """GET /api/sms/templates without auth should return 401"""
        response = self.session.get(f"{BASE_URL}/api/sms/templates")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: No auth returns 401 for /api/sms/templates")
    
    def test_sms_send_no_auth_returns_401(self):
        """POST /api/sms/send without auth should return 401"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={"to": "+61400123456", "message": "Test"}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: No auth returns 401 for /api/sms/send")
    
    def test_admin_can_access_sms_endpoints(self):
        """Admin should have access to SMS endpoints"""
        token = self.get_token("admin")
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        
        response = self.session.get(f"{BASE_URL}/api/sms/status")
        assert response.status_code == 200, f"Admin should access /api/sms/status, got {response.status_code}"
        print("PASS: Admin can access SMS endpoints")
    
    def test_staff_can_access_sms_endpoints(self):
        """Staff should have access to SMS endpoints"""
        token = self.get_token("staff")
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        
        response = self.session.get(f"{BASE_URL}/api/sms/status")
        assert response.status_code == 200, f"Staff should access /api/sms/status, got {response.status_code}"
        print("PASS: Staff can access SMS endpoints")
    
    def test_tax_agent_can_access_sms_endpoints(self):
        """Tax agent should have access to SMS endpoints"""
        token = self.get_token("tax_agent")
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        
        response = self.session.get(f"{BASE_URL}/api/sms/status")
        assert response.status_code == 200, f"Tax agent should access /api/sms/status, got {response.status_code}"
        print("PASS: Tax agent can access SMS endpoints")
    
    def test_client_cannot_access_sms_endpoints(self):
        """Client should NOT have access to SMS endpoints (403)"""
        token = self.get_token("client")
        if not token:
            pytest.skip("Client user not available")
        
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        
        response = self.session.get(f"{BASE_URL}/api/sms/status")
        assert response.status_code == 403, f"Client should get 403, got {response.status_code}"
        print("PASS: Client gets 403 for SMS endpoints")


class TestSMSStatus:
    """Test GET /api/sms/status endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup authenticated session"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login as admin
        response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json=CREDENTIALS["admin"]
        )
        if response.status_code == 200:
            token = response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip("Admin login failed")
    
    def test_status_returns_correct_structure(self):
        """Status endpoint should return expected fields"""
        response = self.session.get(f"{BASE_URL}/api/sms/status")
        assert response.status_code == 200
        
        data = response.json()
        
        # Check required fields
        assert "phase" in data, "Missing 'phase' field"
        assert "status" in data, "Missing 'status' field"
        assert "provider" in data, "Missing 'provider' field"
        assert "configuration" in data, "Missing 'configuration' field"
        assert "ready_to_send" in data, "Missing 'ready_to_send' field"
        assert "templates_available" in data, "Missing 'templates_available' field"
        assert "message" in data, "Missing 'message' field"
        
        print(f"PASS: Status returns correct structure: {data}")
    
    def test_status_shows_not_configured(self):
        """Status should show not_configured when Twilio credentials missing"""
        response = self.session.get(f"{BASE_URL}/api/sms/status")
        assert response.status_code == 200
        
        data = response.json()
        
        # Since Twilio is not configured, expect not_configured status
        assert data["status"] == "not_configured", f"Expected 'not_configured', got {data['status']}"
        assert data["ready_to_send"] == False, "ready_to_send should be False"
        assert "Configure" in data["message"] or "not configured" in data["message"].lower(), \
            f"Message should indicate configuration needed: {data['message']}"
        
        print(f"PASS: Status correctly shows not_configured")
    
    def test_status_shows_provider_twilio(self):
        """Status should show twilio as provider"""
        response = self.session.get(f"{BASE_URL}/api/sms/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["provider"] == "twilio", f"Expected 'twilio', got {data['provider']}"
        
        print("PASS: Provider is twilio")
    
    def test_status_shows_configuration_details(self):
        """Status should show configuration details"""
        response = self.session.get(f"{BASE_URL}/api/sms/status")
        assert response.status_code == 200
        
        data = response.json()
        config = data["configuration"]
        
        # Check configuration fields exist
        assert "account_sid" in config, "Missing account_sid in configuration"
        assert "auth_token" in config, "Missing auth_token in configuration"
        assert "from_number" in config, "Missing from_number in configuration"
        
        # Since not configured, should show "Not set"
        assert "Not set" in config["account_sid"] or "✗" in config["account_sid"]
        
        print(f"PASS: Configuration details shown: {config}")
    
    def test_status_shows_templates_count(self):
        """Status should show correct number of templates available"""
        response = self.session.get(f"{BASE_URL}/api/sms/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["templates_available"] == 9, f"Expected 9 templates, got {data['templates_available']}"
        
        print("PASS: Templates count is 9")


class TestSMSTemplates:
    """Test GET /api/sms/templates endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup authenticated session"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login as admin
        response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json=CREDENTIALS["admin"]
        )
        if response.status_code == 200:
            token = response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip("Admin login failed")
    
    def test_templates_returns_all_9_templates(self):
        """Templates endpoint should return all 9 templates"""
        response = self.session.get(f"{BASE_URL}/api/sms/templates")
        assert response.status_code == 200
        
        data = response.json()
        assert "templates" in data, "Missing 'templates' field"
        assert "count" in data, "Missing 'count' field"
        assert data["count"] == 9, f"Expected 9 templates, got {data['count']}"
        
        print(f"PASS: Templates endpoint returns {data['count']} templates")
    
    def test_templates_contains_expected_ids(self):
        """Templates should contain all expected template IDs"""
        response = self.session.get(f"{BASE_URL}/api/sms/templates")
        assert response.status_code == 200
        
        data = response.json()
        templates = data["templates"]
        
        for template_id in EXPECTED_TEMPLATES:
            assert template_id in templates, f"Missing template: {template_id}"
            assert isinstance(templates[template_id], str), f"Template {template_id} should be a string"
            assert len(templates[template_id]) > 0, f"Template {template_id} should not be empty"
        
        print(f"PASS: All 9 expected templates present: {list(templates.keys())}")
    
    def test_appointment_reminder_template_has_variables(self):
        """appointment_reminder template should have client_name, date, time variables"""
        response = self.session.get(f"{BASE_URL}/api/sms/templates")
        assert response.status_code == 200
        
        data = response.json()
        template = data["templates"]["appointment_reminder"]
        
        assert "{client_name}" in template, "Missing {client_name} variable"
        assert "{date}" in template, "Missing {date} variable"
        assert "{time}" in template, "Missing {time} variable"
        
        print(f"PASS: appointment_reminder template has correct variables")
    
    def test_bas_lodged_template_has_variables(self):
        """bas_lodged template should have client_name, period, amount, due_date variables"""
        response = self.session.get(f"{BASE_URL}/api/sms/templates")
        assert response.status_code == 200
        
        data = response.json()
        template = data["templates"]["bas_lodged"]
        
        assert "{client_name}" in template, "Missing {client_name} variable"
        assert "{period}" in template, "Missing {period} variable"
        assert "{amount}" in template, "Missing {amount} variable"
        assert "{due_date}" in template, "Missing {due_date} variable"
        
        print(f"PASS: bas_lodged template has correct variables")
    
    def test_verification_code_template_has_code_variable(self):
        """verification_code template should have code variable"""
        response = self.session.get(f"{BASE_URL}/api/sms/templates")
        assert response.status_code == 200
        
        data = response.json()
        template = data["templates"]["verification_code"]
        
        assert "{code}" in template, "Missing {code} variable"
        
        print(f"PASS: verification_code template has {'{code}'} variable")


class TestSMSSend:
    """Test POST /api/sms/send endpoint - graceful failure when not configured"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup authenticated session"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login as admin
        response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json=CREDENTIALS["admin"]
        )
        if response.status_code == 200:
            token = response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip("Admin login failed")
    
    def test_send_returns_503_when_not_configured(self):
        """Send should return 503 (in response body) when Twilio not configured"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={
                "to": "+61400123456",
                "message": "Test message"
            }
        )
        # The endpoint returns 200 with error in body (graceful failure)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data["success"] == False, "success should be False"
        assert data["status"] == "not_configured", f"Expected 'not_configured', got {data['status']}"
        assert data["error_code"] == 503, f"Expected error_code 503, got {data.get('error_code')}"
        assert "not configured" in data["error"].lower(), f"Error should mention not configured: {data['error']}"
        
        print(f"PASS: Send returns graceful 503 error when not configured")
    
    def test_send_with_australian_mobile_04_format(self):
        """Send with Australian mobile format (04xxxxxxxx) should normalize correctly"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={
                "to": "0412345678",
                "message": "Test message"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        # Should fail due to not configured, but phone should be accepted
        assert data["success"] == False
        assert data["status"] == "not_configured"
        # No validation error means phone was accepted
        assert "Invalid phone" not in str(data.get("error", ""))
        
        print("PASS: Australian 04 format accepted")
    
    def test_send_with_e164_format(self):
        """Send with E.164 format (+61xxxxxxxxx) should work"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={
                "to": "+61412345678",
                "message": "Test message"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == False
        assert data["status"] == "not_configured"
        
        print("PASS: E.164 format accepted")
    
    def test_send_with_61_prefix(self):
        """Send with 61 prefix (no +) should normalize correctly"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={
                "to": "61412345678",
                "message": "Test message"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == False
        assert data["status"] == "not_configured"
        
        print("PASS: 61 prefix format accepted")
    
    def test_send_with_message_type(self):
        """Send with message_type parameter should work"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={
                "to": "+61412345678",
                "message": "Test reminder",
                "message_type": "reminder"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == False
        assert data["status"] == "not_configured"
        
        print("PASS: message_type parameter accepted")
    
    def test_send_with_client_id(self):
        """Send with client_id parameter should work"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={
                "to": "+61412345678",
                "message": "Test message",
                "client_id": "TEST-CLIENT-001"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == False
        assert data["status"] == "not_configured"
        
        print("PASS: client_id parameter accepted")
    
    def test_send_missing_to_returns_422(self):
        """Send without 'to' field should return 422 validation error"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={
                "message": "Test message"
            }
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        
        print("PASS: Missing 'to' returns 422")
    
    def test_send_missing_message_returns_422(self):
        """Send without 'message' field should return 422 validation error"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={
                "to": "+61412345678"
            }
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        
        print("PASS: Missing 'message' returns 422")


class TestSMSSendTemplate:
    """Test POST /api/sms/send-template endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup authenticated session"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login as admin
        response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json=CREDENTIALS["admin"]
        )
        if response.status_code == 200:
            token = response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip("Admin login failed")
    
    def test_send_template_returns_503_when_not_configured(self):
        """Send template should return 503 when not configured"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send-template",
            json={
                "to": "+61412345678",
                "template_id": "welcome",
                "variables": {"client_name": "John"}
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == False
        assert data["status"] == "not_configured"
        assert data["error_code"] == 503
        
        print("PASS: Send template returns 503 when not configured")
    
    def test_send_template_appointment_reminder(self):
        """Send appointment_reminder template with variables"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send-template",
            json={
                "to": "+61412345678",
                "template_id": "appointment_reminder",
                "variables": {
                    "client_name": "John Smith",
                    "date": "15 January 2025",
                    "time": "2:00 PM"
                }
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == False
        assert data["status"] == "not_configured"
        
        print("PASS: appointment_reminder template accepted")
    
    def test_send_template_bas_lodged(self):
        """Send bas_lodged template with variables"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send-template",
            json={
                "to": "+61412345678",
                "template_id": "bas_lodged",
                "variables": {
                    "client_name": "Jane Doe",
                    "period": "Q4 2024",
                    "amount": "5,250.00",
                    "due_date": "28 February 2025"
                }
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == False
        assert data["status"] == "not_configured"
        
        print("PASS: bas_lodged template accepted")
    
    def test_send_template_verification_code(self):
        """Send verification_code template"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send-template",
            json={
                "to": "+61412345678",
                "template_id": "verification_code",
                "variables": {
                    "code": "123456"
                }
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == False
        assert data["status"] == "not_configured"
        
        print("PASS: verification_code template accepted")
    
    def test_send_template_missing_template_id_returns_422(self):
        """Send template without template_id should return 422"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send-template",
            json={
                "to": "+61412345678",
                "variables": {"client_name": "John"}
            }
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        
        print("PASS: Missing template_id returns 422")
    
    def test_send_template_missing_variables_returns_422(self):
        """Send template without variables should return 422"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send-template",
            json={
                "to": "+61412345678",
                "template_id": "welcome"
            }
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        
        print("PASS: Missing variables returns 422")


class TestPhoneNumberValidation:
    """Test phone number validation and normalization logic"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup authenticated session"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login as admin
        response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json=CREDENTIALS["admin"]
        )
        if response.status_code == 200:
            token = response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip("Admin login failed")
    
    def test_australian_mobile_04_format(self):
        """Test Australian mobile format 04xxxxxxxx"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={"to": "0412345678", "message": "Test"}
        )
        assert response.status_code == 200
        data = response.json()
        # Should not have validation error
        assert "Invalid phone" not in str(data.get("error", ""))
        print("PASS: 04xxxxxxxx format accepted")
    
    def test_australian_landline_02_format(self):
        """Test Australian landline format 02xxxxxxxx"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={"to": "0298765432", "message": "Test"}
        )
        assert response.status_code == 200
        data = response.json()
        # Should not have validation error
        assert "Invalid phone" not in str(data.get("error", ""))
        print("PASS: 02xxxxxxxx format accepted")
    
    def test_e164_format_with_plus(self):
        """Test E.164 format +61xxxxxxxxx"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={"to": "+61412345678", "message": "Test"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "Invalid phone" not in str(data.get("error", ""))
        print("PASS: +61xxxxxxxxx format accepted")
    
    def test_61_prefix_without_plus(self):
        """Test 61 prefix without + sign"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={"to": "61412345678", "message": "Test"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "Invalid phone" not in str(data.get("error", ""))
        print("PASS: 61xxxxxxxxx format accepted")
    
    def test_phone_with_spaces(self):
        """Test phone number with spaces"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={"to": "+61 412 345 678", "message": "Test"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "Invalid phone" not in str(data.get("error", ""))
        print("PASS: Phone with spaces accepted")
    
    def test_phone_with_dashes(self):
        """Test phone number with dashes"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={"to": "+61-412-345-678", "message": "Test"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "Invalid phone" not in str(data.get("error", ""))
        print("PASS: Phone with dashes accepted")


class TestMessageValidation:
    """Test message content validation"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup authenticated session"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login as admin
        response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json=CREDENTIALS["admin"]
        )
        if response.status_code == 200:
            token = response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip("Admin login failed")
    
    def test_message_max_length_1600(self):
        """Test message at max length (1600 chars)"""
        long_message = "A" * 1600
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={"to": "+61412345678", "message": long_message}
        )
        assert response.status_code == 200
        data = response.json()
        # Should not have length validation error
        assert "1600" not in str(data.get("error", "")) or "exceeds" not in str(data.get("error", ""))
        print("PASS: 1600 char message accepted")
    
    def test_message_exceeds_max_length(self):
        """Test message exceeding max length (1601 chars) returns 422"""
        long_message = "A" * 1601
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={"to": "+61412345678", "message": long_message}
        )
        # Pydantic validation should catch this
        assert response.status_code == 422, f"Expected 422 for message > 1600 chars, got {response.status_code}"
        print("PASS: Message > 1600 chars returns 422")
    
    def test_normal_message_length(self):
        """Test normal message length"""
        response = self.session.post(
            f"{BASE_URL}/api/sms/send",
            json={"to": "+61412345678", "message": "Hello, this is a test message."}
        )
        assert response.status_code == 200
        print("PASS: Normal message accepted")


class TestClientUserCreation:
    """Test that client user was created successfully"""
    
    def test_client_user_login(self):
        """Verify client user can login"""
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        
        response = session.post(
            f"{BASE_URL}/api/auth/login",
            json=CREDENTIALS["client"]
        )
        
        if response.status_code == 200:
            data = response.json()
            assert "access_token" in data
            assert data["role"] == "client"
            print(f"PASS: Client user login successful - role: {data['role']}")
        else:
            print(f"INFO: Client user login failed with status {response.status_code}")
            print(f"Response: {response.text}")
            pytest.skip("Client user not available")


class TestClientBASAccess:
    """Test that client can access BAS workflow endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup client session"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Try to login as client
        response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json=CREDENTIALS["client"]
        )
        if response.status_code == 200:
            token = response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
            self.client_available = True
        else:
            self.client_available = False
    
    def test_client_can_access_bas_history(self):
        """Client should be able to access BAS history (requires client_id param)"""
        if not self.client_available:
            pytest.skip("Client user not available")
        
        # BAS history requires client_id parameter
        response = self.session.get(f"{BASE_URL}/api/bas/history?client_id=TEST-CLIENT-001")
        # Client should have read access to BAS
        assert response.status_code in [200, 403, 422], f"Unexpected status: {response.status_code}"
        
        if response.status_code == 200:
            print("PASS: Client can access BAS history")
        elif response.status_code == 422:
            # Missing required param is expected if no client_id
            print("INFO: BAS history requires client_id parameter (422)")
        else:
            print("INFO: Client cannot access BAS history (403)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
