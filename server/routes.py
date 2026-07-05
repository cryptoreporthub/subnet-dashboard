### All API and web routes.###
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from server.config import *  # noqa: F403

logger = logging.getLogger(__name__)
router = APIRouter()

