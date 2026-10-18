import pickle
import time
import unittest

import streamlit as st

from streamlit_persist_session._persister import (
    _decrypt_and_unpack,
    _get_fernet_instance,
    _pack_and_encrypt,
    _resolve_secret_key,
    persist,
)


@persist("test-default-state")
class DefaultState:
    def __init__(self):
        self.count = 42
        self.secret_token = "sensitive_token_123"


@persist("test-excluded-state", exclude_fields=["secret_token"])
class ExcludedState:
    def __init__(self):
        self.count = 100
        self.secret_token = "sensitive_token_123"
        self._ephemeral_cached = "memory_only"


class TestSecurityEnhancements(unittest.TestCase):
    def setUp(self):
        # Reset streamlit session state
        st.session_state.clear()

    def test_encryption_of_saved_file(self):
        """Test that the saved file is encrypted with Fernet and cannot be unpickled directly."""
        key = _resolve_secret_key("test-secret-key")
        fernet = _get_fernet_instance(key)

        inst = DefaultState()
        inst.count = 99
        inst.secret_token = "super_secret_api_key"

        # Pack and encrypt
        encrypted_bytes = _pack_and_encrypt(inst, fernet, ttl=3600)

        # 1. Verify it starts with Fernet header 'gAAAAA'
        self.assertTrue(
            encrypted_bytes.startswith(b"gAAAAA"),
            "Payload should be Fernet-encrypted format (starting with gAAAAA)",
        )

        # 2. Verify plain unpickling fails
        with self.assertRaises(Exception):
            pickle.loads(encrypted_bytes)

        # 3. Verify sensitive string is NOT found in cleartext within the bytes
        self.assertNotIn(
            b"super_secret_api_key",
            encrypted_bytes,
            "Cleartext secret must not appear in encrypted payload",
        )

        # 4. Decrypt and verify state is restored
        restored = _decrypt_and_unpack(encrypted_bytes, fernet)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.count, 99)
        self.assertEqual(restored.secret_token, "super_secret_api_key")

    def test_exclude_fields_and_ephemeral(self):
        """Test that exclude_fields and _ephemeral_* attributes are omitted from disk persistence."""
        key = _resolve_secret_key("test-secret-key")
        fernet = _get_fernet_instance(key)

        inst = ExcludedState()
        inst.count = 77
        inst.secret_token = "secret_will_not_persist"
        inst._ephemeral_cached = "ephemeral_will_not_persist"

        # In-memory values exist
        self.assertEqual(inst.secret_token, "secret_will_not_persist")
        self.assertEqual(inst._ephemeral_cached, "ephemeral_will_not_persist")

        # Pack and encrypt
        encrypted_bytes = _pack_and_encrypt(inst, fernet, ttl=3600)

        # Decrypt to check state
        restored = _decrypt_and_unpack(encrypted_bytes, fernet)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.count, 77)
        # Excluded field must NOT be in restored instance
        self.assertFalse(
            hasattr(restored, "secret_token"),
            "Excluded field should not be present in restored disk state",
        )
        self.assertFalse(
            hasattr(restored, "_ephemeral_cached"),
            "Ephemeral field should not be present in restored disk state",
        )

    def test_ttl_expiration(self):
        """Test that an expired session payload is discarded."""
        key = _resolve_secret_key("test-secret-key")
        fernet = _get_fernet_instance(key)

        inst = DefaultState()
        inst.count = 50

        # Create payload with 1 second TTL
        encrypted_bytes = _pack_and_encrypt(inst, fernet, ttl=1)

        # Immediately should be valid
        restored = _decrypt_and_unpack(encrypted_bytes, fernet)
        self.assertIsNotNone(restored)

        # Wait for expiration
        time.sleep(1.1)

        # After TTL, it must return None
        expired_restored = _decrypt_and_unpack(encrypted_bytes, fernet)
        self.assertIsNone(
            expired_restored,
            "Expired session must return None",
        )

    def test_tampered_or_invalid_key_fails(self):
        """Test that data encrypted with one key cannot be decrypted with another."""
        key1 = _resolve_secret_key("key-1")
        key2 = _resolve_secret_key("key-2")

        fernet1 = _get_fernet_instance(key1)
        fernet2 = _get_fernet_instance(key2)

        inst = DefaultState()
        encrypted_bytes = _pack_and_encrypt(inst, fernet1, ttl=3600)

        # Attempt to decrypt with wrong key
        restored = _decrypt_and_unpack(encrypted_bytes, fernet2)
        self.assertIsNone(restored, "Decryption with wrong key must fail and return None")

    def test_old_plain_pickle_handling(self):
        """Test that legacy cleartext pickle file is rejected safely."""
        key = _resolve_secret_key("test-key")
        fernet = _get_fernet_instance(key)

        # Plain pickle bytes
        plain_pickle = pickle.dumps({"test": "data"})

        # Decryption attempt must fail gracefully
        restored = _decrypt_and_unpack(plain_pickle, fernet)
        self.assertIsNone(restored, "Plain pickle data must be rejected as invalid token")


if __name__ == "__main__":
    unittest.main()
