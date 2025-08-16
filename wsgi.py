# wsgi.py
import importlib, traceback
from flask import Flask, Response

def _resolve_app():
    try:
        m = importlib.import_module("app")  # app.py を読み込む
        return getattr(m, "app")            # app.py 内の app = Flask(__name__)
    except Exception:
        err = traceback.format_exc()
        a = Flask(__name__)
        @a.get("/")
        def down_root():
            return "WSGI import failed. See /__wsgi_error", 500
        @a.get("/__wsgi_error")
        def werr():
            return Response(err, mimetype="text/plain", status=500)
        return a

app = _resolve_app()
