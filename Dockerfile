FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN echo "VERSION: 3.8.3" > VERSION.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
