FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data/leagues
RUN mkdir -p /root/.streamlit && echo '\
[server]\n\
headless = true\n\
address = "0.0.0.0"\n\
port = 8501\n\
baseUrlPath = "27"\n\
maxUploadSize = 50\n\
enableXsrfProtection = false\n\
[browser]\n\
gatherUsageStats = false\n\
' > /root/.streamlit/config.toml
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl --fail http://localhost:8501/27/_stcore/health || exit 1
ENTRYPOINT ["streamlit", "run", "app.py"]
