"""Route registration."""
def register_routes(app):
    from server.routes.indicators import router as indicators_router
    app.include_router(indicators_router)
    from server.routes.judges import router as judges_router
    app.include_router(judges_router)
    from server.routes.learning import router as learning_router
    app.include_router(learning_router)
    from server.routes.mindmap import router as mindmap_router
    app.include_router(mindmap_router)
    from server.routes.pumps import router as pumps_router
    app.include_router(pumps_router)
    from server.routes.simivision import router as simivision_router
    app.include_router(simivision_router)
    from server.routes.subnets import router as subnets_router
    app.include_router(subnets_router)
    from server.routes.system import router as system_router
    app.include_router(system_router)
    from server.routes.tokens import router as tokens_router
    app.include_router(tokens_router)
    from server.routes.web import router as web_router
    app.include_router(web_router)
