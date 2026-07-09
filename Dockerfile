FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN echo "VERSION: 3.8.1" > VERSION.txt

COPY . .

EXPOSE 8080

CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:8080"]
