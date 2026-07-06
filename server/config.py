# """Server configuration."""
import json
import logging
import math
import os
import sys
import threading
import time
import traceback
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Add the current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetchers.taomarketcap import get_all_subnets, get_subnet_data

# Create the FastAPI app
app = FastAPI(title="Subnet Dashboard", version="1.0.0")

# Mount static files at /static
app.mount("/static", StaticFiles(directory="static"), name="static")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Main route
@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Health check
@app.get("/health")
async def health():
    return {"status": "healthy"}

# ... rest of the file ...