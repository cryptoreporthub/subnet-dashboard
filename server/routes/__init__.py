"""Route registration."""
def register_routes(app):
    from server.routes.system import router as system_router
    app.include_router(system_router)
