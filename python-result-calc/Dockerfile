FROM python:3.9-slim

WORKDIR /usr/src/app

RUN pip install numpy==1.26.4

RUN pip install --no-cache-dir torch==2.1.2+cpu torchvision==0.16.2+cpu \
    --extra-index-url https://download.pytorch.org/whl/cpu
RUN apt-get update && apt-get install -y tesseract-ocr
COPY requirements.txt requirements.txt
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "result-calc.py"]
