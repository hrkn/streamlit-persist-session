# Streamlit Persist Session

A Python library/utility designed for **Persistent data across page reloads** in Streamlit applications using cryptographically signed browser cookies and AES-encrypted local state files.

### Demo
A live demo application is available at: [https://persist-session.streamlit.app/](https://persist-session.streamlit.app/)

## Purpose

The primary goal of `streamlit-persist-session` is to provide **Persistent data across page reloads**.

By default, Streamlit's built-in `st.session_state` resets whenever a user refreshes/reloads their browser tab or when the WebSocket connection is interrupted. This component bypasses that limitation by automatically preserving decorated class instances on the server side, indexing them via a unique session ID stored securely in the client's browser cookies.

## Features

- **Automatic Persistence**: A simple class decorator (`@streamlit_persist_session.persist`) wraps your state class, intercepting attribute reads/writes to keep the state synchronized.
  > [!IMPORTANT]
  > The decorated class **must be pickleable** (i.e., defined at the module level, not nested inside functions or other classes) because the state is serialized using Python's `pickle` module.
- **Secure by Design**:
  - **AES Encryption**: State files are encrypted using authenticated cryptography (`Fernet`) before being written to disk, preventing cleartext exposure of sensitive data in temporary directories (mitigating CWE-312 / CWE-922).
  - **Strict Permissions**: Files are created with `0600` permissions (owner read/write only) to protect against unauthorized local access in shared server environments.
  - **HMAC Cookie Signing**: Signs session tokens using HMAC-SHA256 with a unique server-side secret key to prevent client-side tampering.
  - **Path Traversal Protection**: Strict input validation of session IDs (UUIDv4).
  - **Configurable TTL & Expiration**: Session state and browser cookies can expire automatically based on a configurable time-to-live (`ttl`, default: 24 hours).
  - **Memory-Only Attributes**: Sensitive credentials or tokens can be kept in-memory (`st.session_state`) only, omitting them from disk storage via `exclude_fields` or the `_ephemeral_` prefix.
- **Session Lifecycles**: Supports explicit state clearing via `state.clear_cookie_state()`.

## Key Architecture

`streamlit-persist-session` wraps `streamlit_cookies_controller` to implement:
1. **Cookie Key Allocation & HMAC Verification**: Allocates a unique identifier to browser cookies and validates authenticity with an HMAC signature.
2. **Encrypted Storage & Restoration**: Automatically serializes and encrypts Python objects to local server files on attribute mutation, restoring and decrypting state seamlessly upon page reload.

## Integration with Authentication

> [!NOTE]
> If your application implements login session management using Streamlit's native `st.login()`, this manually managed cookie state functionality might overlap. In such cases, you should reference `st.user` to manage user sessions and state rather than using this component.

## Usage Examples

### Basic Usage (100% Backward-Compatible)

By default, encryption, strict file permissions, and 24-hour TTL are applied automatically without any extra configuration:

```python
import streamlit_persist_session

# Decorated class must be pickleable at the module level.
@streamlit_persist_session.persist("app-state")
class AppState:
    def __init__(self):
        self.count = 0
```

### Advanced Security Configuration

You can customize secret keys, set expiration times, and exclude sensitive credentials from being stored on disk:

```python
import streamlit_persist_session

@streamlit_persist_session.persist(
    "secure-user-state",
    # Session TTL in seconds (e.g. 1 hour; default is 86400 seconds = 24 hours)
    ttl=3600,
    # Exclude sensitive attributes from disk storage (stored only in-memory in st.session_state)
    exclude_fields=["api_token", "oauth_session"],
    # Optional custom encryption key (otherwise resolved from st.secrets or environment variable)
    secret_key="my-app-secret-passphrase",
)
class SecureAppState:
    def __init__(self):
        self.count = 0
        self.api_token = "secret_access_token"  # Excluded from disk file
        self._ephemeral_cache = {}              # _ephemeral_* is also excluded from disk file
```

## Secret Key Resolution Priority

When no `secret_key` is passed directly to the decorator, the key is resolved in the following order:
1. `st.secrets["STREAMLIT_PERSIST_SECRET_KEY"]` or `st.secrets["persist_secret_key"]`
2. Environment variable: `STREAMLIT_PERSIST_SECRET_KEY`
3. Auto-generated 32-byte key stored securely with `0600` permissions on the server.

## Directory Structure

- [src/streamlit_persist_session/](src/streamlit_persist_session/): Core package containing the decorator logic.
  - [__init__.py](src/streamlit_persist_session/__init__.py): Package entry point exposing the decorator.
  - [_persister.py](src/streamlit_persist_session/_persister.py): Internal implementation of state persistence and encryption.
- [main.py](main.py): A demo Streamlit application demonstrating state persistence.
- [tests/](tests/): Unit and security regression test suites.
- [pyproject.toml](pyproject.toml): Project metadata, package definition, and dependencies.
- [README.md](README.md): This documentation.

## Prerequisites

Ensure you have the following installed:

- Python 3.13 or higher
- [uv](https://github.com/astral-sh/uv) (recommended Python package and workflow manager)
- [mise](https://mise.jdx.dev/) (optional, runtime management tool)

## Getting Started

### 1. Installation & Dependency Setup

Initialize and synchronize the virtual environment with the necessary dependencies:

```bash
uv sync
```

### 2. Run the Demo Application

Launch the interactive Streamlit dashboard:

```bash
uv run streamlit run main.py
```

If the browser does not open automatically, visit the URL output in your terminal (usually `http://localhost:8501`).

Alternatively, you can try the hosted version at [https://persist-session.streamlit.app/](https://persist-session.streamlit.app/).

## How It Works

1. **Instantiation & Placeholder**: When the app first loads, the decorator checks whether the session cookie exists. If cookies are not yet loaded, a temporary placeholder instance is returned while the cookie controller retrieves data.
2. **State Serialization & Encryption**:
   - Every modification to persisted state attributes triggers serialization and AES encryption (`Fernet`).
   - The encrypted payload includes expiration timestamps (`expires_at`) and metadata.
   - The file is saved to the server's temporary directory with restricted `0600` permissions, using a random UUIDv4 as the filename.
   - A signed token (`<UUID>.<HMAC-SHA256>`) is set in the client's browser cookies with matching expiration headers.
3. **Restoration & Verification**: On page reload or session reconnection, the cookie is read, HMAC signature is verified, the file payload is decrypted, and TTL expiration is checked. If verified, the original state object is restored.
4. **Invalidation & Clean up**: If a session has expired, the HMAC verification fails, or the `clear_cookie_state()` method is invoked, the temporary file is deleted, browser cookies are removed, and `st.session_state` is updated.

## License

This project is licensed under the MIT License.
See the [LICENSE](LICENSE) file for the full license text.
