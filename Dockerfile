FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# MoviePyに必要
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# ★起動前に import を検証（ログに "import OK" が出ればパス）
CMD ["/bin/sh", "-lc", "python -c \"import sys; import moviepy, importlib; print(sys.version); print('moviepy', moviepy.__version__); importlib.import_module('moviepy.editor'); print('import OK');\" && exec gunicorn app:app -b 0.0.0.0:8000 -w 1 -k gthread --threads 8 --timeout 600"]
