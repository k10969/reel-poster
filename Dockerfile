FROM python:3.9-slim
WORKDIR /app
COPY . .
RUN python -m pip install --upgrade pip
RUN apt-get update --allow-releaseinfo-change && apt-get install -y --no-install-recommends ffmpeg libmagic1 libsm6 libxext6 libxrender1 libfontconfig1 libavcodec-dev libavformat-dev libswscale-dev && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
CMD ["streamlit", "run", "app.py", "--server.port", "8080", "--server.enableCORS", "false", "--server.headless", "true"]
