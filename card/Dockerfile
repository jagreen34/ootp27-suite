# The Card (:8505). Builds from the REPO ROOT so quakers.py, draft_board.py and
# data_store.py land at /app — exactly one copy of every constant, shared with
# the command-line tools and with verify_draftday.py.
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir streamlit pandas
COPY data_store.py quakers.py draft_board.py /app/
COPY card/app.py /app/app.py
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["streamlit","run","app.py","--server.port=8501","--server.address=0.0.0.0","--server.headless=true"]
