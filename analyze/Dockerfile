FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir flask openpyxl gunicorn
COPY ootp_analyze.py app.py ./
# The registry self-test (63 checks) runs at BUILD time. A failing constant never ships.
RUN python3 ootp_analyze.py verify
EXPOSE 8506
# One league export (~1,500 players) holds a worker ~90s, hence the long timeout.
# -w 2 sync workers: app.py swaps sys.stdout process-globally during verify, which is
# only safe with one request per process. Do NOT switch to gthread/--threads.
CMD ["gunicorn","-b","0.0.0.0:8506","-w","2","--timeout","300","--access-logfile","-","app:app"]
