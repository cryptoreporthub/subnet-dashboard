"""Subnet Dashboard server package."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os

def create_app():
    app = FastAPI()
    # CORS
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    # Static files
    app.mount("/static", StaticFiles(directory="static"), name="static")
    # Register routes
    from server.routes import register_routes
    register_routes(app)
    return app
