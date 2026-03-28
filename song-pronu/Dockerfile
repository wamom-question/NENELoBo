FROM python:3.9-slim
WORKDIR /usr/src/app

COPY . .
RUN pip install flask requests python-dotenv

CMD ["python3", "pronunciation.py"]
