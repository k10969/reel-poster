# -*- coding: utf-8 -*-
import importlib, traceback
from flask import Response

# 最小ガード：確実に app を公開
app = None

def _resolve_app():
    global app
    try:
        m = importlib.import_module("app")  # app.py
        app = getattr(m, "app")
        return app
    except Exception as e:
        err = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        from flask import Flask
        app_fallback = Flask(__name__)

        @app_fallback.get("/")
        def root():
            return "WSGI import failed. See /__wsgi_error", 500

        @app_fallback.get("/__wsgi_error")
        def werr():
            return Response("WSGI import failed:\n"+err, mimetype="text/plain", status=500)

        return app_fallback

app = _resolve_app()
