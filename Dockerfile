FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && pip install --no-cache-dir -r requirements.txt \
    && rm -rf /var/lib/apt/lists/*

RUN echo "VERSION: 3.8.3" > VERSION.txt

COPY . .

# Robust boot: chmod entrypoints at build time AND invoke via shell so
# exec-bit/shebang quirks in the image can never block machine startup.
RUN chmod +x scripts/fly_web_entrypoint.sh scripts/fly_worker_entrypoint.sh

EXPOSE 8080

CMD ["sh", "./scripts/fly_web_entrypoint.sh"]
