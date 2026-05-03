FROM python:3.11-alpine
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY torr_to_strm.py .
CMD ["python", "-u", "torr_to_strm.py"]
