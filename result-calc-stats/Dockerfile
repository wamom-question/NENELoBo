FROM python:3.11-slim

RUN pip install --upgrade pip
COPY requirements.txt .
RUN pip install -r requirements.txt

WORKDIR /app
COPY app/ /app/

EXPOSE 53743

CMD ["streamlit", "run", "dashboard.py", "--server.port=53743", "--server.address=0.0.0.0"]