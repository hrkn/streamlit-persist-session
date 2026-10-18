import base64
from datetime import datetime, timedelta
import hashlib
import hmac
import logging
import os
import pickle
import sys
import tempfile
import threading
import time
from typing import Any, Optional, Sequence, Union
import uuid

from cryptography.fernet import Fernet, InvalidToken
import streamlit as st
from streamlit_cookies_controller import CookieController

# Thread-local storage to prevent infinite recursion during pickle.load
_local = threading.local()


def _get_unpickling_flag() -> bool:
    return getattr(_local, "is_unpickling", False)


def _set_unpickling_flag(val: bool):
    _local.is_unpickling = val


# Logger setup
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


def _resolve_secret_key(custom_key: Union[str, bytes, None] = None) -> bytes:
    """
    Resolve the secret key with the following priority:
    1. Explicit custom_key parameter
    2. st.secrets["STREAMLIT_PERSIST_SECRET_KEY"] or st.secrets["persist_secret_key"]
    3. os.environ["STREAMLIT_PERSIST_SECRET_KEY"]
    4. Auto-generated 32-byte key stored securely with 0600 permissions
    """
    if custom_key is not None:
        if isinstance(custom_key, str):
            custom_key = custom_key.encode("utf-8")
        return custom_key

    # Check st.secrets safely
    try:
        if hasattr(st, "secrets"):
            if "STREAMLIT_PERSIST_SECRET_KEY" in st.secrets:
                key_val = st.secrets["STREAMLIT_PERSIST_SECRET_KEY"]
                return key_val.encode("utf-8") if isinstance(key_val, str) else key_val
            if "persist_secret_key" in st.secrets:
                key_val = st.secrets["persist_secret_key"]
                return key_val.encode("utf-8") if isinstance(key_val, str) else key_val
    except Exception as e:
        LOGGER.debug(f"Could not read key from st.secrets: {e}")

    # Check environment variable
    env_key = os.environ.get("STREAMLIT_PERSIST_SECRET_KEY")
    if env_key:
        return env_key.encode("utf-8")

    # Fallback: file in temp dir with strict 0600 permissions
    temp_dir = tempfile.gettempdir()
    secret_path = os.path.join(temp_dir, ".streamlit_cookie_secret.key")
    if os.path.exists(secret_path):
        try:
            with open(secret_path, "rb") as f:
                key = f.read()
                if len(key) >= 32:
                    return key
        except Exception as e:
            LOGGER.warning(f"Failed to read existing secret key: {e}")

    # Generate a new 32-byte key
    key = os.urandom(32)
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(secret_path, flags, 0o600)
        with open(fd, "wb", closefd=True) as f:
            f.write(key)
        try:
            os.chmod(secret_path, 0o600)
        except Exception:
            pass
    except Exception as e:
        LOGGER.error(f"Failed to save secret key to {secret_path}: {e}")
    return key


def _get_fernet_instance(raw_secret: bytes) -> Fernet:
    """Derive a URL-safe base64 32-byte key suitable for Fernet."""
    try:
        decoded = base64.urlsafe_b64decode(raw_secret)
        if len(decoded) == 32:
            return Fernet(raw_secret)
    except Exception:
        pass
    digest = hashlib.sha256(raw_secret).digest()
    b64_key = base64.urlsafe_b64encode(digest)
    return Fernet(b64_key)


def _secure_write_file(file_path: str, data: bytes) -> None:
    """Write bytes to file with strict 0600 permissions."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd = os.open(file_path, flags, 0o600)
    try:
        with open(fd, "wb", closefd=True) as f:
            f.write(data)
    except Exception:
        raise
    try:
        os.chmod(file_path, 0o600)
    except Exception:
        pass


def _pack_and_encrypt(
    instance: Any,
    fernet: Fernet,
    ttl: Optional[int],
) -> bytes:
    """Serialize the instance state and encrypt it along with expiration metadata."""
    _set_unpickling_flag(True)
    try:
        instance_bytes = pickle.dumps(instance)
    finally:
        _set_unpickling_flag(False)

    now = time.time()
    payload = {
        "version": 1,
        "created_at": now,
        "expires_at": (now + ttl) if ttl else None,
        "data": instance_bytes,
    }
    raw_payload = pickle.dumps(payload)
    return fernet.encrypt(raw_payload)


def _decrypt_and_unpack(
    encrypted_data: bytes,
    fernet: Fernet,
) -> Optional[Any]:
    """Decrypt the payload and unpack the persisted instance if valid and not expired."""
    try:
        decrypted_payload = fernet.decrypt(encrypted_data)
    except (InvalidToken, Exception) as e:
        LOGGER.warning(f"Failed to decrypt state payload: {e}")
        return None

    try:
        payload = pickle.loads(decrypted_payload)
        if not isinstance(payload, dict):
            return None

        # Check expiration
        expires_at = payload.get("expires_at")
        if expires_at is not None and time.time() > expires_at:
            LOGGER.info("Persisted session has expired based on TTL.")
            return None

        data_bytes = payload.get("data")
        if not data_bytes:
            return None

        _set_unpickling_flag(True)
        try:
            return pickle.loads(data_bytes)
        finally:
            _set_unpickling_flag(False)
    except Exception as e:
        LOGGER.error(f"Failed to deserialize decrypted state: {e}")
        return None


def persist(
    cookie_key: str,
    *,
    secret_key: Union[str, bytes, None] = None,
    ttl: Optional[int] = 86400,
    exclude_fields: Optional[Sequence[str]] = None,
):
    """
    A class decorator to persist class instances securely via browser cookies and encrypted local state files.

    Args:
        cookie_key: Name of the cookie used to store the signed session token.
        secret_key: Secret key for AES encryption and HMAC signatures. If omitted, it is automatically
            resolved from Streamlit secrets, environment variables, or a securely created server key.
        ttl: Time-to-live in seconds for the session state and cookie (default: 86400 seconds = 24 hours).
            Set to None for indefinite persistence.
        exclude_fields: List of attribute names to exclude from disk persistence. These fields will be kept
            only in-memory (`st.session_state`) and never written to temporary files. Attributes prefixed
            with `_ephemeral_` are also automatically excluded from disk persistence.
    """
    exclude_fields_set = set(exclude_fields) if exclude_fields else set()

    def decorator(cls):
        # 1. Verify pickleability at decoration time.
        if "<locals>" in cls.__qualname__:
            raise TypeError(
                f"Class '{cls.__name__}' is defined locally (e.g. inside a function) "
                f"and cannot be pickled. Ensure the class is defined at the module level."
            )

        # Verify that the class module is valid
        module_name = cls.__module__
        if not module_name or module_name not in sys.modules:
            raise TypeError(
                f"Class '{cls.__name__}' is defined in an invalid or unimportable module: '{module_name}'."
            )

        # Store original class methods
        orig_new = cls.__new__
        orig_init = cls.__init__
        orig_setattr = cls.__setattr__
        orig_delattr = cls.__delattr__
        orig_getstate = getattr(cls, "__getstate__", None)
        orig_setstate = getattr(cls, "__setstate__", None)

        def custom_getstate(self):
            if orig_getstate is not None:
                state = orig_getstate(self)
                if isinstance(state, dict):
                    state = dict(state)
                else:
                    return state
            else:
                state = dict(self.__dict__)

            # Filter out internal tracking attributes, ephemeral attributes, and excluded fields
            keys_to_remove = [
                k
                for k in state
                if k.startswith("_cookie_")
                or k.startswith("_controller_")
                or k.startswith("_ephemeral_")
                or k in exclude_fields_set
            ]
            for k in keys_to_remove:
                state.pop(k, None)
            return state

        def custom_setstate(self, state):
            if orig_setstate is not None:
                orig_setstate(self, state)
            else:
                self.__dict__.update(state)

        def custom_new(cls_, *args, **kwargs):
            # If we are currently loading the object via pickle.load, bypass cookie resolution
            # to avoid infinite recursion.
            if _get_unpickling_flag():
                if orig_new is object.__new__:
                    return object.__new__(cls_)
                else:
                    return orig_new(cls_)

            # Run a one-time validation on the first instantiation to ensure the instance is pickleable.
            if not getattr(cls_, "_pickle_validated", False):
                try:
                    if orig_new is object.__new__:
                        test_inst = object.__new__(cls_)
                    else:
                        try:
                            test_inst = orig_new(cls_)
                        except TypeError:
                            test_inst = object.__new__(cls_)
                    pickle.dumps(test_inst)
                    cls_._pickle_validated = True
                except Exception as e:
                    raise TypeError(
                        f"Instances of class '{cls_.__name__}' cannot be pickled: {e}"
                    )

            state_key = f"_cookie_persisted_{cookie_key}"
            controller_key = f"cookies_{cookie_key}"

            # A. Check session state cache
            if state_key in st.session_state:
                cached = st.session_state[state_key]
                if isinstance(cached, cls_):
                    return cached

            # B. Check if CookieController has loaded cookies from the client browser
            if controller_key not in st.session_state:
                if orig_new is object.__new__:
                    temp_instance = object.__new__(cls_)
                else:
                    temp_instance = orig_new(cls_, *args, **kwargs)

                temp_instance._is_temp_placeholder = True
                temp_instance._initialized = False

                _ = CookieController(key=controller_key)
                LOGGER.debug(
                    f"Cookie controller '{controller_key}' not ready. Returning placeholder."
                )
                return temp_instance

            # C. Cookie controller is ready!
            controller = CookieController(key=controller_key)
            cookie_val = controller.get(cookie_key)
            temp_dir = tempfile.gettempdir()
            loaded_instance = None
            valid_session = False

            raw_secret = _resolve_secret_key(secret_key)
            fernet = _get_fernet_instance(raw_secret)

            if cookie_val:
                try:
                    parts = cookie_val.split(".", 1)
                    if len(parts) == 2:
                        uid, mac_hex = parts
                        uuid_obj = uuid.UUID(uid)
                        if uuid_obj.version != 4:
                            raise ValueError("Not a UUIDv4")

                        # Verify HMAC signature
                        expected_mac = hmac.new(
                            raw_secret, uid.encode(), hashlib.sha256
                        ).hexdigest()
                        if hmac.compare_digest(mac_hex, expected_mac):
                            file_path = os.path.join(temp_dir, uid)
                            if os.path.exists(file_path):
                                try:
                                    with open(file_path, "rb") as f:
                                        encrypted_data = f.read()
                                    loaded_instance = _decrypt_and_unpack(
                                        encrypted_data, fernet
                                    )
                                except Exception as read_err:
                                    LOGGER.warning(
                                        f"Failed to read encrypted state file: {read_err}"
                                    )
                                    loaded_instance = None

                                if isinstance(loaded_instance, cls_):
                                    try:
                                        loaded_instance._cookie_uuid = uid
                                        loaded_instance._cookie_key = cookie_key
                                        loaded_instance._controller_key = controller_key
                                        loaded_instance._is_temp_placeholder = False
                                    except Exception as attr_err:
                                        LOGGER.warning(
                                            f"Failed to restore persistent attributes on loaded instance: {attr_err}"
                                        )
                                    valid_session = True
                                    LOGGER.info(
                                        f"Successfully loaded and decrypted persisted instance: {uid}"
                                    )
                except Exception as e:
                    LOGGER.error(f"Error loading persisted instance: {e}")

            if valid_session and loaded_instance is not None:
                st.session_state[state_key] = loaded_instance
                return loaded_instance

            # D. Clear invalid/expired cookie & file
            if cookie_val:
                try:
                    parts = cookie_val.split(".", 1)
                    if len(parts) == 2:
                        uid = parts[0]
                        uuid.UUID(uid)
                        file_path = os.path.join(temp_dir, uid)
                        if os.path.exists(file_path):
                            os.remove(file_path)
                except Exception as e:
                    LOGGER.debug(f"Failed to delete invalid state file: {e}")
                try:
                    controller.remove(cookie_key)
                except Exception as e:
                    LOGGER.debug(f"Failed to remove invalid cookie: {e}")
                LOGGER.info(
                    "Persisted state cleared due to verification failure or expiration."
                )

            # E. Create a brand new instance
            if orig_new is object.__new__:
                new_instance = object.__new__(cls_)
            else:
                new_instance = orig_new(cls_, *args, **kwargs)

            new_instance._is_temp_placeholder = False
            new_instance._initialized = False
            new_instance._cookie_uuid = str(uuid.uuid4())
            new_instance._cookie_key = cookie_key
            new_instance._controller_key = controller_key

            # Set the persistent cookie in browser
            mac = hmac.new(
                raw_secret, new_instance._cookie_uuid.encode(), hashlib.sha256
            ).hexdigest()

            cookie_options = {}
            if ttl is not None:
                cookie_options["max_age"] = ttl
                cookie_options["expires"] = datetime.now() + timedelta(seconds=ttl)

            controller.set(
                cookie_key,
                f"{new_instance._cookie_uuid}.{mac}",
                **cookie_options,
            )
            LOGGER.info(
                f"Generated new persisted instance: {new_instance._cookie_uuid}"
            )

            st.session_state[state_key] = new_instance
            return new_instance

        def custom_init(self, *args, **kwargs):
            if getattr(self, "_initialized", False):
                return

            # Run original __init__
            orig_init(self, *args, **kwargs)
            self._initialized = True

            # Save initialized state to file (if not a temporary placeholder)
            if not getattr(self, "_is_temp_placeholder", False):
                self._save_to_file()

        def _save_to_file(self):
            if getattr(self, "_is_temp_placeholder", False):
                return
            cookie_uuid = getattr(self, "_cookie_uuid", None)
            if not cookie_uuid:
                LOGGER.warning("Cannot save to file: '_cookie_uuid' attribute is missing.")
                return
            try:
                temp_dir = tempfile.gettempdir()
                file_path = os.path.join(temp_dir, cookie_uuid)
                current_raw_secret = _resolve_secret_key(secret_key)
                current_fernet = _get_fernet_instance(current_raw_secret)
                encrypted_data = _pack_and_encrypt(self, current_fernet, ttl)
                _secure_write_file(file_path, encrypted_data)
                LOGGER.debug(f"Saved encrypted state to file: {cookie_uuid}")
            except Exception as e:
                LOGGER.error(f"Failed to save state to file: {e}")

        def custom_setattr(self, name, value):
            orig_setattr(self, name, value)
            # Prevent auto-saving during initial __init__ or on temp placeholders
            if (
                getattr(self, "_initialized", False)
                and not getattr(self, "_is_temp_placeholder", False)
                and not name.startswith("_cookie_")
                and not name.startswith("_controller_")
                and not name.startswith("_ephemeral_")
                and name not in exclude_fields_set
            ):
                self._save_to_file()

        def custom_delattr(self, name):
            orig_delattr(self, name)
            # Prevent auto-saving for temp placeholders or internal flags
            if (
                getattr(self, "_initialized", False)
                and not getattr(self, "_is_temp_placeholder", False)
                and not name.startswith("_cookie_")
                and not name.startswith("_controller_")
                and not name.startswith("_ephemeral_")
                and name not in exclude_fields_set
            ):
                self._save_to_file()

        def clear_cookie_state(self):
            """Remove the persistent cookie, delete the temp file, and clear the session state cache."""
            if getattr(self, "_is_temp_placeholder", False):
                LOGGER.debug("Cannot clear cookie state: instance is a temporary placeholder.")
                return

            LOGGER.info("Clearing cookie state and temporary file.")

            # 1. Remove cookie from browser
            controller_key = getattr(self, "_controller_key", None)
            cookie_key_val = getattr(self, "_cookie_key", None)
            if controller_key and cookie_key_val:
                try:
                    controller = CookieController(key=controller_key)
                    controller.remove(cookie_key_val)
                except Exception as e:
                    LOGGER.warning(f"Failed to remove cookie: {e}")

            # 2. Delete the state file from temp directory
            cookie_uuid = getattr(self, "_cookie_uuid", None)
            if cookie_uuid:
                temp_dir = tempfile.gettempdir()
                file_path = os.path.join(temp_dir, cookie_uuid)
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        LOGGER.warning(f"Failed to delete file {file_path}: {e}")

            # 3. Clear session state cache
            if cookie_key_val:
                state_key_val = f"_cookie_persisted_{cookie_key_val}"
                if state_key_val in st.session_state:
                    del st.session_state[state_key_val]

        # Override/attach methods in-place
        cls.__new__ = staticmethod(custom_new)
        cls.__init__ = custom_init
        cls.__getstate__ = custom_getstate
        cls.__setstate__ = custom_setstate
        cls._save_to_file = _save_to_file
        cls.__setattr__ = custom_setattr
        cls.__delattr__ = custom_delattr
        cls.clear_cookie_state = clear_cookie_state

        return cls

    return decorator
