# wsgi.py — ultra-robust loader (app / application / create_app を探索 + 失敗時に /__wsgi_error で全文表示)
import sys, traceback, importlib

def _resolve_app():
    m = importlib.import_module("app")  # app.py を読み込む
    # 1) 変数 app
    if hasattr(m, "app"):
        return getattr(m, "app")
    # 2) 変数 application
    if hasattr(m, "application"):
        return getattr(m, "application")
    # 3) ファクトリ create_app()
    if hasattr(m, "create_app") and callable(m.create_app):
        return m.create_app()
    raise RuntimeError("No Flask app found in app.py (expected: app/application/create_app).")

try:
    app = _resolve_app()  # gunicorn は wsgi:app を見る
except Exception as e:
    ERR = "WSGI import failed:\n" + "".join(traceback.format_exception(type(e), e, e.__traceback__))
    print(ERR, file=sys.stderr)
    from flask import Flask, Response
    app = Flask(__name__)

    @app.get("/")
    def _root():
        return "WSGIは実際のapp.pyのインポートに失敗しました。/__wsgi_error を開いて詳細を確認してください。", 500

    @app.get("/__wsgi_error")
    def _err():
        return Response(ERR or "No captured error.", mimetype="text/plain", status=500)
