FROM python:3.12-slim

WORKDIR /app

# Install Node.js for npm
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Update VERSION to force rebuild
RUN echo "VERSION: 3.6.0 $(date +%Y%m%d%H%M%S)" > VERSION.txt

COPY . .

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "30", "server:app"]