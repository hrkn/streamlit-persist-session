# Streamlit Persist Session

A Python library/utility designed for **Persistent data across page reloads** in Streamlit applications using cryptographically signed browser cookies and local state files.

## Purpose

The primary goal of `streamlit-persist-session` is to provide **Persistent data across page reloads**.

By default, Streamlit's built-in `st.session_state` resets whenever a user refreshes/reloads their browser tab or when the WebSocket connection is interrupted. This component bypasses that limitation by automatically preserving decorated class instances on the server side, indexing them via a unique session ID stored securely in the client's browser cookies.

## Features

- **Automatic Persistence**: A simple class decorator (`@streamlit_persist_session.persist`) wraps your state class, intercepting attribute reads/writes to keep the state synchronized.
  > [!IMPORTANT]
  > The decorated class **must be pickleable** (i.e., defined at the module level, not nested inside functions or other classes) because the state is serialized using Python's `pickle` module.
- **Secure by Design**:
  - Cryptographically signs session cookies using HMAC-SHA256 with a unique server-side secret key to prevent client-side tampering.
  - Strict input validation of session IDs (UUIDv4) to prevent path traversal or file injection attacks.
- **Session Lifecycles**: Supports explicit state clearing via `state.clear_cookie_state()`.

## Key Architecture

`streamlit-persist-session` wraps `streamlit_cookies_controller` to implement:
1. **Cookie Key Allocation & HMAC Verification**: Allocates a unique identifier to the browser cookies and runs an authenticity check using HMAC signatures.
2. **Data Storage & Restoration**: Automatically serializes python objects to local server files on attribute mutation, and restores the original state on page reload.

## Integration with Authentication

> [!NOTE]
> If your application implements login session management using Streamlit's native `st.login()`, this manually managed cookie state functionality might overlap. In such cases, you should reference `st.user` to manage user sessions and state rather than using this component.

## Usage Example

Here is a basic example of how to persist a simple counter class.

```python
import streamlit_persist_session

# Note: The decorated class must be pickleable.
@streamlit_persist_session.persist("app-state")
class AppState:
    def __init__(self):
        self.count = 0

    # ... see main.py for full example
```

## Directory Structure

- [src/streamlit_persist_session/](file:///c:/Users/mcs/Documents/develop/streamlit-cookie/src/streamlit_persist_session/): Core package containing the decorator logic.
  - [__init__.py](file:///c:/Users/mcs/Documents/develop/streamlit-cookie/src/streamlit_persist_session/__init__.py): Package entry point exposing the decorator.
  - [_persister.py](file:///c:/Users/mcs/Documents/develop/streamlit-cookie/src/streamlit_persist_session/_persister.py): Internal implementation of the state persistence.
- [main.py](file:///c:/Users/mcs/Documents/develop/streamlit-cookie/main.py): A demo Streamlit application demonstrating state persistence.
- [pyproject.toml](file:///c:/Users/mcs/Documents/develop/streamlit-cookie/pyproject.toml): Project metadata, package definition, and dependencies.
- [README.md](file:///c:/Users/mcs/Documents/develop/streamlit-cookie/README.md): This documentation.

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

## How It Works

1. **Instantiation & Placeholder**: When the app first loads, the custom decorator checks if the session cookie exists. If the cookies are not yet loaded, a temporary placeholder instance is returned while the cookie controller retrieves data.
2. **State Serialization**:
   - Every modification to the state attributes triggers a serialization step (`pickle.dump`) to a secure temporary file on the server.
   - The filename is a random UUIDv4, which is stored as a signed value (`<UUID>.<HMAC-signature>`) in the browser's cookies.
3. **Restoration**: On page reload or session reconnection, the cookie is read, signature verified, and the state object is deserialized (`pickle.load`), keeping the state intact.
4. **Clean up**: When clicking the "Clear cookies and temporary files" button, the temporary file is deleted, browser cookies are removed, and `st.session_state` is updated.

## License

This project is licensed under the MIT License.
See the [LICENSE](file:///c:/Users/mcs/Documents/develop/streamlit-cookie/LICENSE) file for the full license text.
