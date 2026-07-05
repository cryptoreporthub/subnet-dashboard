"""Route registration."""
def register_routes(app):
    from server.routes.all import router
    app.include_router(router)
