FROM python:3.11-alpine
RUN pip install --no-cache-dir requests
WORKDIR /app
COPY torr_to_strm.py /app/
CMD ["python", "-u", "torr_to_strm.py"]