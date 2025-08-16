# wsgi.py  — 安全インポート版
import sys, traceback

try:
    # app.py の Flask インスタンスを読み込む（app = Flask(__name__) が必要）
    from app import app as application
    app = application  # gunicorn が参照する名前
except Exception as e:
    # 失敗した場合でも 500 を返す簡易アプリを起動してログを可視化
    print("WSGI import failed:", e, file=sys.stderr)
    traceback.print_exc()
    from flask import Flask
    app = Flask(__name__)

    @app.get("/")
    def _fallback():
        return "WSGI failed to import real app.py. Check Render logs for details.", 500
