import logging
import time
import streamlit as st
import streamlit_cookies_controller

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s"
)

# クッキーコントローラーの初期化
cookie_controller = streamlit_cookies_controller.CookieController()

if 'count' not in st.session_state:
    st.session_state.count = 0

if 'count_loaded' not in st.session_state:
    st.session_state.count_loaded = False

# まだクッキーからロードしていない場合、クッキーからの読み込みを試みる
if not st.session_state.count_loaded:
    cookie_count = cookie_controller.get("count")
    if cookie_count is not None:
        st.session_state.count = int(cookie_count)
        st.session_state.count_loaded = True
        logging.info(f"SUCCESS: count loaded from cookie: {st.session_state.count}")

# ボタンのレイアウト
col1, col2 = st.columns(2)

with col1:
    # ボタンをクリックするとカウントアップ
    if st.button("カウントアップ", use_container_width=True):
        st.session_state.count += 1
        cookie_controller.set("count", st.session_state.count)
        # 自分でセットした場合はロード完了したとみなす
        st.session_state.count_loaded = True
        logging.info(f"count incremented to: {st.session_state.count}")

with col2:
    # ボタンをクリックするとクッキーをクリア
    if st.button("クッキーをクリア", use_container_width=True):
        cookie_controller.remove("count")
        st.session_state.count = 0
        st.session_state.count_loaded = True
        logging.info("Cookie 'count' removed and session state reset.")
        time.sleep(0.5)
        st.rerun()

# 現在のカウントを表示
st.write("現在のカウント：", st.session_state.count)
