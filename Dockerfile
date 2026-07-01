FROM python:3.12-slim

WORKDIR /app

# NOTE: Node.js/npm was previously installed here but is unused by this app
# (no package.json, no build step). Removing it speeds up the build and avoids
# the Node.js 18 EOL deprecation noise. The app is pure Python (FastAPI/uvicorn).

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Update VERSION to force rebuild
RUN echo "VERSION: 3.6.0 $(date +%Y%m%d%H%M%S)" > VERSION.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]