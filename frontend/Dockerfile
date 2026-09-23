FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir streamlit==1.40.0 requests==2.32.3

COPY app.py .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]