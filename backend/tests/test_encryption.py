"""
Unit Tests for Encryption Service

Tests encryption/decryption of:
- TFN (Tax File Number)
- ABN (Australian Business Number)
- ACN (Australian Company Number)
- Bank Account Details

Run with: pytest tests/test_encryption.py -v
"""

import os
import pytest
from unittest.mock import patch

# Set up test encryption key before importing
TEST_ENCRYPTION_KEY = "dGVzdC1lbmNyeXB0aW9uLWtleS0zMi1ieXRlcy0h"  # Base64 test key

# Generate a valid Fernet key for testing
from cryptography.fernet import Fernet
VALID_TEST_KEY = Fernet.generate_key().decode()


class TestEncryptionService:
    """Test suite for EncryptionService class."""
    
    @pytest.fixture(autouse=True)
    def setup_encryption_key(self):
        """Set up encryption key for each test."""
        # Clear any cached Fernet instance
        from utils.encryption import clear_fernet_cache
        clear_fernet_cache()
        
        # Set the test key
        os.environ['ENCRYPTION_KEY'] = VALID_TEST_KEY
        
        yield
        
        # Clean up
        if 'ENCRYPTION_KEY' in os.environ:
            del os.environ['ENCRYPTION_KEY']
        clear_fernet_cache()
    
    @pytest.fixture
    def service(self):
        """Create encryption service instance."""
        from utils.encryption import EncryptionService
        return EncryptionService()
    
    # ==================== TFN TESTS ====================
    
    def test_encrypt_decrypt_tfn_roundtrip(self, service):
        """Test TFN encryption and decryption round-trip."""
        original_tfn = "123456789"
        
        encrypted = service.encrypt_tfn(original_tfn)
        decrypted = service.decrypt_tfn(encrypted)
        
        assert decrypted == original_tfn
        assert encrypted != original_tfn  # Should be different
    
    def test_encrypt_tfn_validation(self, service):
        """Test TFN validation."""
        from utils.encryption import ValidationError
        
        # Valid TFN (9 digits)
        encrypted = service.encrypt_tfn("123456789")
        assert encrypted is not None
        
        # Valid TFN (8 digits)
        encrypted = service.encrypt_tfn("12345678")
        assert encrypted is not None
        
        # Invalid TFN (too short)
        with pytest.raises(ValidationError):
            service.encrypt_tfn("1234567")
        
        # Invalid TFN (too long)
        with pytest.raises(ValidationError):
            service.encrypt_tfn("1234567890")
        
        # Invalid TFN (with letters)
        with pytest.raises(ValidationError):
            service.encrypt_tfn("12345678A")
    
    def test_mask_tfn(self, service):
        """Test TFN masking."""
        assert service.mask_tfn("123456789") == "*****6789"
        assert service.mask_tfn("123456789", visible=6) == "***456789"
        assert service.mask_tfn("1234") == "1234"
        assert service.mask_tfn("") == ""
    
    def test_encrypt_tfn_strips_formatting(self, service):
        """Test that TFN encryption strips spaces and dashes."""
        tfn_with_spaces = "123 456 789"
        tfn_with_dashes = "123-456-789"
        plain_tfn = "123456789"
        
        enc1 = service.encrypt_tfn(tfn_with_spaces, validate=False)
        enc2 = service.encrypt_tfn(tfn_with_dashes, validate=False)
        
        # Both should decrypt to the same value
        assert service.decrypt_tfn(enc1) == plain_tfn
        assert service.decrypt_tfn(enc2) == plain_tfn
    
    # ==================== ABN TESTS ====================
    
    def test_encrypt_decrypt_abn_roundtrip(self, service):
        """Test ABN encryption and decryption round-trip."""
        # Valid ABN with correct checksum
        original_abn = "51824753556"
        
        encrypted = service.encrypt_abn(original_abn)
        decrypted = service.decrypt_abn(encrypted)
        
        assert decrypted == original_abn
        assert encrypted != original_abn
    
    def test_encrypt_abn_validation(self, service):
        """Test ABN validation."""
        from utils.encryption import ValidationError
        
        # Valid ABN
        encrypted = service.encrypt_abn("51824753556")
        assert encrypted is not None
        
        # Invalid ABN (wrong length)
        with pytest.raises(ValidationError):
            service.encrypt_abn("1234567890")
        
        # Invalid ABN (wrong checksum)
        with pytest.raises(ValidationError):
            service.encrypt_abn("12345678901")
    
    def test_abn_checksum_validation(self, service):
        """Test ABN checksum algorithm."""
        # Known valid ABNs
        valid_abns = [
            "51824753556",  # ATO example
            "53004085616",  # Example
        ]
        
        for abn in valid_abns:
            assert service._validate_abn_checksum(abn) is True
        
        # Invalid checksum
        assert service._validate_abn_checksum("12345678901") is False
    
    def test_mask_abn(self, service):
        """Test ABN masking."""
        assert service.mask_abn("51824753556") == "*******3556"
        assert service.mask_abn("51824753556", visible=6) == "*****753556"
    
    # ==================== ACN TESTS ====================
    
    def test_encrypt_decrypt_acn_roundtrip(self, service):
        """Test ACN encryption and decryption round-trip."""
        original_acn = "123456789"
        
        encrypted = service.encrypt_acn(original_acn)
        decrypted = service.decrypt_acn(encrypted)
        
        assert decrypted == original_acn
        assert encrypted != original_acn
    
    def test_encrypt_acn_validation(self, service):
        """Test ACN validation."""
        from utils.encryption import ValidationError
        
        # Valid ACN
        encrypted = service.encrypt_acn("123456789")
        assert encrypted is not None
        
        # Invalid ACN (wrong length)
        with pytest.raises(ValidationError):
            service.encrypt_acn("12345678")
    
    def test_mask_acn(self, service):
        """Test ACN masking."""
        assert service.mask_acn("123456789") == "*****6789"
    
    # ==================== BANK DETAILS TESTS ====================
    
    def test_encrypt_decrypt_bank_account_roundtrip(self, service):
        """Test bank account encryption and decryption round-trip."""
        bsb = "123456"
        account = "12345678"
        
        encrypted = service.encrypt_bank_account(bsb, account)
        decrypted = service.decrypt_bank_account(encrypted)
        
        assert decrypted['bsb'] == bsb
        assert decrypted['account'] == account
        assert encrypted != bsb and encrypted != account
    
    def test_encrypt_bank_account_validation(self, service):
        """Test bank account validation."""
        from utils.encryption import ValidationError
        
        # Valid bank details
        encrypted = service.encrypt_bank_account("123456", "12345678")
        assert encrypted is not None
        
        # Invalid BSB (wrong length)
        with pytest.raises(ValidationError):
            service.encrypt_bank_account("12345", "12345678")
        
        # Invalid account (too short)
        with pytest.raises(ValidationError):
            service.encrypt_bank_account("123456", "12345")
        
        # Invalid account (too long)
        with pytest.raises(ValidationError):
            service.encrypt_bank_account("123456", "12345678901")
    
    def test_mask_bsb(self, service):
        """Test BSB masking."""
        assert service.mask_bsb("123456") == "***-456"
        assert service.mask_bsb("123") == "123"
    
    def test_mask_account_number(self, service):
        """Test account number masking."""
        assert service.mask_account_number("12345678") == "****5678"
        assert service.mask_account_number("12345678", visible=6) == "**345678"
    
    # ==================== BATCH OPERATIONS TESTS ====================
    
    def test_encrypt_client_sensitive_data(self, service):
        """Test batch encryption of client data."""
        result = service.encrypt_client_sensitive_data(
            tfn="123456789",
            abn="51824753556",
            acn="123456789",
            bsb="123456",
            account_number="12345678"
        )
        
        assert result['tfn_encrypted'] is not None
        assert result['tfn_last_four'] == "6789"
        assert result['abn_encrypted'] is not None
        assert result['acn_encrypted'] is not None
        assert result['bank_encrypted'] is not None
    
    def test_encrypt_client_sensitive_data_partial(self, service):
        """Test batch encryption with partial data."""
        result = service.encrypt_client_sensitive_data(
            tfn="123456789",
            abn=None,
            acn=None
        )
        
        assert result['tfn_encrypted'] is not None
        assert result['abn_encrypted'] is None
        assert result['acn_encrypted'] is None
        assert result['bank_encrypted'] is None
    
    def test_decrypt_client_sensitive_data(self, service):
        """Test batch decryption of client data."""
        # First encrypt
        encrypted = service.encrypt_client_sensitive_data(
            tfn="123456789",
            abn="51824753556",
            bsb="123456",
            account_number="12345678"
        )
        
        # Then decrypt
        decrypted = service.decrypt_client_sensitive_data(
            tfn_encrypted=encrypted['tfn_encrypted'],
            abn_encrypted=encrypted['abn_encrypted'],
            bank_encrypted=encrypted['bank_encrypted']
        )
        
        assert decrypted['tfn'] == "123456789"
        assert decrypted['abn'] == "51824753556"
        assert decrypted['bsb'] == "123456"
        assert decrypted['account_number'] == "12345678"
    
    # ==================== ERROR HANDLING TESTS ====================
    
    def test_decrypt_with_wrong_key_fails(self, service):
        """Test that decryption fails with wrong key."""
        from utils.encryption import DecryptionError, clear_fernet_cache
        
        original = "123456789"
        encrypted = service.encrypt_tfn(original)
        
        # Change the key
        clear_fernet_cache()
        os.environ['ENCRYPTION_KEY'] = Fernet.generate_key().decode()
        
        # Create new service with different key
        from utils.encryption import EncryptionService
        new_service = EncryptionService()
        
        with pytest.raises(DecryptionError):
            new_service.decrypt_tfn(encrypted)
    
    def test_encryption_without_key_fails(self):
        """Test that encryption fails without key."""
        from utils.encryption import EncryptionService, KeyNotConfiguredError, clear_fernet_cache
        
        clear_fernet_cache()
        if 'ENCRYPTION_KEY' in os.environ:
            del os.environ['ENCRYPTION_KEY']
        
        service = EncryptionService()
        
        with pytest.raises(KeyNotConfiguredError):
            service.encrypt_tfn("123456789")
    
    def test_empty_value_raises_error(self, service):
        """Test that empty values raise validation errors."""
        from utils.encryption import ValidationError
        
        with pytest.raises(ValidationError):
            service.encrypt_tfn("")
        
        with pytest.raises(ValidationError):
            service.encrypt_abn("")
        
        with pytest.raises(ValidationError):
            service.encrypt_bank_account("", "12345678")


class TestEncryptionServiceConfiguration:
    """Test encryption service configuration."""
    
    def test_is_encryption_configured_true(self):
        """Test is_encryption_configured returns True when key is set."""
        from utils.encryption import is_encryption_configured, clear_fernet_cache
        
        clear_fernet_cache()
        os.environ['ENCRYPTION_KEY'] = VALID_TEST_KEY
        
        assert is_encryption_configured() is True
        
        del os.environ['ENCRYPTION_KEY']
        clear_fernet_cache()
    
    def test_is_encryption_configured_false(self):
        """Test is_encryption_configured returns False when key is not set."""
        from utils.encryption import is_encryption_configured, clear_fernet_cache
        
        clear_fernet_cache()
        if 'ENCRYPTION_KEY' in os.environ:
            del os.environ['ENCRYPTION_KEY']
        
        assert is_encryption_configured() is False


class TestNoPlaintextLogging:
    """Verify that plaintext sensitive data is never logged."""
    
    @pytest.fixture(autouse=True)
    def setup_encryption_key(self):
        """Set up encryption key for each test."""
        from utils.encryption import clear_fernet_cache
        clear_fernet_cache()
        os.environ['ENCRYPTION_KEY'] = VALID_TEST_KEY
        yield
        if 'ENCRYPTION_KEY' in os.environ:
            del os.environ['ENCRYPTION_KEY']
        clear_fernet_cache()
    
    def test_tfn_not_in_debug_logs(self, caplog):
        """Test that full TFN is never logged."""
        import logging
        from utils.encryption import EncryptionService
        
        caplog.set_level(logging.DEBUG)
        
        service = EncryptionService()
        tfn = "123456789"
        
        encrypted = service.encrypt_tfn(tfn)
        _ = service.decrypt_tfn(encrypted)
        
        # Check that full TFN is not in any log messages
        for record in caplog.records:
            assert tfn not in record.message
            # Last 4 digits may appear for audit purposes
            assert "12345" not in record.message  # First 5 digits should never appear
    
    def test_bank_details_not_in_debug_logs(self, caplog):
        """Test that full bank details are never logged."""
        import logging
        from utils.encryption import EncryptionService
        
        caplog.set_level(logging.DEBUG)
        
        service = EncryptionService()
        bsb = "123456"
        account = "12345678"
        
        encrypted = service.encrypt_bank_account(bsb, account)
        _ = service.decrypt_bank_account(encrypted)
        
        # Check that full values are not in any log messages
        for record in caplog.records:
            assert bsb not in record.message
            assert account not in record.message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
