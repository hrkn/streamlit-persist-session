import logging
import time

import streamlit as st

import streamlit_persist_session

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")


# 1. Define and decorate the class you want to persist
@streamlit_persist_session.persist("app-state")
class AppState:
    def __init__(self):
        self.count = 0


# 2. Create the class instance
state = AppState()

# 3. Wait for cookie loading to complete
# On the initial execution, the CookieController fetches cookie values from the browser
# and triggers a rerun. We display a loading message during this process.
if getattr(state, "_is_temp_placeholder", False):
    st.info("Waiting for cookies to load...")
    st.stop()

# 4. Render main UI
st.title("Streamlit Persist Session Demo")

# Current count display
st.write(f"### Current Count: **{state.count}**")

# Debug information including UUID and key
st.markdown("---")
st.markdown("#### Debug Information")
st.markdown(f"- **Persisted UUID (Filename):** `{getattr(state, '_cookie_uuid', 'N/A')}`")
st.markdown(f"- **Cookie Key:** `{getattr(state, '_cookie_key', 'N/A')}`")
st.markdown("---")

# Action buttons layout
col1, col2 = st.columns(2)

with col1:
    if st.button("Increment", use_container_width=True, type="primary"):
        state.count += 1
        st.success(f"Count incremented! New count: {state.count}")
        time.sleep(0.5)  # Wait needed to apply cookie update against client
        st.rerun()

with col2:
    if st.button("Clear Cookie and Temp File", use_container_width=True):
        state.clear_cookie_state()
        st.warning("Cookie and state file removed. Reloading page...")
        time.sleep(1.0)
        st.rerun()
