# wsgi.py — robust loader
import sys, traceback, importlib

def _load_app():
    try:
        m = importlib.import_module("app")  # app.py
        # 1) 変数 app
        if hasattr(m, "app"):
            return getattr(m, "app")
        # 2) 変数 application
        if hasattr(m, "application"):
            return getattr(m, "application")
        # 3) create_app() ファクトリ
        if hasattr(m, "create_app") and callable(m.create_app):
            return m.create_app()
        raise RuntimeError("No Flask app found in app.py (expected app/application/create_app).")
    except Exception as e:
        raise

try:
    app = _load_app()          # Gunicorn は wsgi:app を見る
except Exception as e:
    # 失敗時にトレースを画面で見れるようフォールバック
    err = "WSGI import failed:\n" + "".join(
        traceback.format_exception(type(e), e, e.__traceback__)
    )
    print(err, file=sys.stderr)
    from flask import Flask, Response
    app = Flask(__name__)

    @app.get("/")
    def _fallback_root():
        return "WSGIは実際のapp.pyのインポートに失敗しました。/__wsgi_error を開いてください。", 500

    @app.get("/__wsgi_error")
    def _err():
        return Response(err, mimetype="text/plain", status=500)
