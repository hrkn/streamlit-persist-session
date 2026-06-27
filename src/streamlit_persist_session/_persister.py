import hashlib
import hmac
import logging
import os
import pickle
import sys
import tempfile
import threading
import uuid

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


def _get_secret_key() -> bytes:
    """Retrieve or generate a 32-byte secret HMAC key stored in the temporary directory."""
    temp_dir = tempfile.gettempdir()
    secret_path = os.path.join(temp_dir, "streamlit_cookie_secret.key")
    if os.path.exists(secret_path):
        try:
            with open(secret_path, "rb") as f:
                key = f.read()
                if len(key) == 32:
                    return key
        except Exception as e:
            LOGGER.warning(f"Failed to read existing secret key: {e}")

    # Generate a new 32-byte key
    key = os.urandom(32)
    try:
        with open(secret_path, "wb") as f:
            f.write(key)
    except Exception as e:
        LOGGER.error(f"Failed to save secret key to {secret_path}: {e}")
    return key


def persist(cookie_key: str):
    """
    A class decorator to persist class instances via browser cookies and local temporary files.

    The decorator checks that the class is pickleable at decoration time.
    It hooks class initialization, attribute modifications, and deletion to sync states automatically.
    """

    def decorator(cls):
        # 1. Verify pickleability at decoration time.
        # Since the class name is not yet bound in the module namespace when the decorator runs,
        # we cannot use pickle.dumps(cls) here. Instead, we inspect its qualification path
        # to ensure it's defined at the module level (not inside a local function).
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

        def custom_new(cls_, *args, **kwargs):
            # If we are currently loading the object via pickle.load, bypass cookie resolution
            # to avoid infinite recursion.
            if _get_unpickling_flag():
                if orig_new is object.__new__:
                    return object.__new__(cls_)
                else:
                    return orig_new(cls_)

            # Run a one-time validation on the first instantiation to ensure the instance is pickleable.
            # At this point, the class name has been bound to the module namespace, so pickle.dumps will work.
            if not getattr(cls_, "_pickle_validated", False):
                try:
                    # Create an uninitialized instance to verify pickleability
                    if orig_new is object.__new__:
                        test_inst = object.__new__(cls_)
                    else:
                        # Fallback to try creating the instance, catching errors if __new__ expects arguments
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
                # Cookie controller is not initialized/ready in session state.
                # Create a temporary placeholder object to render the current frame.
                # Do NOT write to cookies or temp files yet.
                if orig_new is object.__new__:
                    temp_instance = object.__new__(cls_)
                else:
                    temp_instance = orig_new(cls_, *args, **kwargs)

                temp_instance._is_temp_placeholder = True
                temp_instance._initialized = False

                # Instantiate CookieController to trigger cookie loading for the next frame
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

            if cookie_val:
                try:
                    # Parse UUID and HMAC
                    parts = cookie_val.split(".", 1)
                    if len(parts) == 2:
                        uid, mac_hex = parts
                        # Validate UUID format to prevent directory traversal
                        uuid_obj = uuid.UUID(uid)
                        if uuid_obj.version != 4:
                            raise ValueError("Not a UUIDv4")

                        # Verify HMAC signature
                        secret_key = _get_secret_key()
                        expected_mac = hmac.new(
                            secret_key, uid.encode(), hashlib.sha256
                        ).hexdigest()
                        if hmac.compare_digest(mac_hex, expected_mac):
                            file_path = os.path.join(temp_dir, uid)
                            if os.path.exists(file_path):
                                # Load from file using unpickling flag to avoid recursion
                                _set_unpickling_flag(True)
                                try:
                                    with open(file_path, "rb") as f:
                                        loaded_instance = pickle.load(f)
                                finally:
                                    _set_unpickling_flag(False)

                                if isinstance(loaded_instance, cls_):
                                    valid_session = True
                                    LOGGER.info(
                                        f"Successfully loaded persisted instance: {uid}"
                                    )
                except Exception as e:
                    LOGGER.error(f"Error loading persisted instance: {e}")

            if valid_session and loaded_instance is not None:
                # Cache loaded instance in session state
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
                    "Persisted state cleared due to verification failure or missing file."
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
            secret_key = _get_secret_key()
            mac = hmac.new(
                secret_key, new_instance._cookie_uuid.encode(), hashlib.sha256
            ).hexdigest()
            controller.set(cookie_key, f"{new_instance._cookie_uuid}.{mac}")
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
            try:
                temp_dir = tempfile.gettempdir()
                file_path = os.path.join(temp_dir, self._cookie_uuid)
                with open(file_path, "wb") as f:
                    pickle.dump(self, f)
                LOGGER.debug(f"Saved state to file: {self._cookie_uuid}")
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
            ):
                self._save_to_file()

        def clear_cookie_state(self):
            """Remove the persistent cookie, delete the temp file, and clear the session state cache."""
            LOGGER.info("Clearing cookie state and temporary file.")

            # 1. Remove cookie from browser
            try:
                controller = CookieController(key=self._controller_key)
                controller.remove(self._cookie_key)
            except Exception as e:
                LOGGER.warning(f"Failed to remove cookie: {e}")

            # 2. Delete the state file from temp directory
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, self._cookie_uuid)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    LOGGER.warning(f"Failed to delete file {file_path}: {e}")

            # 3. Clear session state cache
            state_key = f"_cookie_persisted_{self._cookie_key}"
            if state_key in st.session_state:
                del st.session_state[state_key]

        # Override/attach methods in-place
        cls.__new__ = staticmethod(custom_new)
        cls.__init__ = custom_init
        cls._save_to_file = _save_to_file
        cls.__setattr__ = custom_setattr
        cls.__delattr__ = custom_delattr
        cls.clear_cookie_state = clear_cookie_state

        return cls

    return decorator
