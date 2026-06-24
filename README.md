# Streamlit + Cookie State Persistence

Streamlit アプリケーションにおいて、ブラウザのクッキーを利用して状態（セッション内のデータ）を永続化するためのサンプルプロジェクトです。

## 概要

本プロジェクトは、`streamlit-cookies-controller` パッケージを使用して、Streamlit アプリケーションのセッション状態（例：クリックカウンターの数値）をユーザーのブラウザクッキーに保存および読み込みする実装を示しています。
通常、Streamlit の `st.session_state` はブラウザのリロードやセッションの切断によってリセットされますが、本実装によってリロード後も状態を維持することが可能になります。

## ディレクトリ構成

- [main.py](file:///c:/Users/mcs/Documents/develop/streamlit-cookie/main.py): アプリケーションのメインエントリーポイント。クッキー制御ロジックとUI定義。
- [pyproject.toml](file:///c:/Users/mcs/Documents/develop/streamlit-cookie/pyproject.toml): プロジェクトの依存関係とメタデータ定義。
- [README.md](file:///c:/Users/mcs/Documents/develop/streamlit-cookie/README.md): 本ドキュメント。

## 前提条件

動作には以下の環境が必要です。

- Python 3.13 以上
- [uv](https://github.com/astral-sh/uv) (依存関係およびパッケージ管理ツール)
- [mise](https://mise.jdx.dev/) (任意: ランタイム管理ツール)

## セットアップ手順

### 1. 依存関係のインストール

プロジェクトのルートディレクトリで以下を実行し、仮想環境の作成と必要なライブラリのインストールを行います。

```bash
uv sync
```

## 起動方法

以下のコマンドを実行して Streamlit アプリケーションを起動します。

```bash
uv run streamlit run main.py
```

起動後、自動的にブラウザが開かない場合は、ターミナルに表示される URL（通常は `http://localhost:8501`）にアクセスしてください。

## 動作と仕組み

1. 画面上の「カウントアップ」ボタンを押すと、カウンターの値が 1 ずつ増加します。
2. 増加した値はブラウザのクッキー (`count`) に保存されます。
3. ブラウザをリロード（F5）しても、クッキーから自動的に前回のカウンター値が読み込まれ、画面に反映されます。
4. サーバー側（[main.py](file:///c:/Users/mcs/Documents/develop/streamlit-cookie/main.py)）では、`logging` を通してクッキーからの読み込み成功ログやカウントアップ時のログを出力します。
