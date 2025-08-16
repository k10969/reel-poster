FROM python:3.13-slim
WORKDIR /app
COPY . .
RUN python -m pip install --upgrade pip
RUN apt-get update --allow-releaseinfo-change && apt-get install -y --no-install-recommends ffmpeg libmagic1
RUN pip install -r requirements.txt
CMD ["streamlit", "run", "app.py", "--server.port", "8080", "--server.enableCORS", "false", "--server.headless", "true"]