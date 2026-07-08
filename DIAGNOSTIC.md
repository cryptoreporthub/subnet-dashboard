# Diagnostic Report

app = FastAPI at line 549
        logger.warning("Failed to stop indicator scheduler: %s", exc)





app = FastAPI(

    title="SimiVision Subnet Dashboard",

    version="3.5.0",

    lifespan=_lifespan,

)





# Mount static files at /static

static mount at line 557
    lifespan=_lifespan,

)





# Mount static files at /static

app.mount("/static", StaticFiles(directory="static"), name="static")



# CORS middleware (replaces Flask's per-response CORS headers)

app.add_middleware(

    CORSMiddleware,

static mount at line 571
)



# Mount static files at /static

_static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

if os.path.isdir(_static_dir):

    app.mount("/static", StaticFiles(directory=_static_dir), name="static")



# Jinja2 templates for server-side rendered dashboard

_templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

templates = Jinja2Templates(directory=_templates_dir)
