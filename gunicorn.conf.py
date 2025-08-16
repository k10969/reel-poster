# gunicorn.conf.py
bind = "0.0.0.0:8000"
workers = 1          # moviepy/ffmpeg はメモリ使うので 1 で安定運用
worker_class = "sync"
timeout = 600        # ← 長めに。動画合成〜Cloudinaryアップで時間がかかる想定
graceful_timeout = 120
keepalive = 5
preload_app = False
