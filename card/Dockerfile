# The Card (:8505). Builds from the REPO ROOT so quakers.py, draft_board.py and
# data_store.py land at /app — exactly one copy of every constant, shared with
# the command-line tools and with verify_draftday.py.
#
# ⚠ baseUrlPath=card is REQUIRED. nginx proxies ootptools.com/card/ through to
# localhost:8505/card/ with the path preserved (same pattern as /rank/), so
# Streamlit has to be told it lives under /card/ or every asset 404s.
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir streamlit pandas
COPY data_store.py quakers.py draft_board.py /app/
COPY card/app.py /app/app.py
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8501/card/_stcore/health')"
CMD ["streamlit","run","app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.baseUrlPath=card"]
