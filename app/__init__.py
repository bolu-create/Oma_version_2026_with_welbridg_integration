from flask import Flask
from app.config import load_configurations, configure_logging
from .views import webhook_blueprint




"""

from flask import Flask

def create_app():
    app = Flask(__name__)
    
    # 👇 Health check route for Render
    @app.route("/")
    def root():
        return "App is running", 200

    # Import and register blueprints
    app.register_blueprint(webhook_blueprint)

    return app
"""

def create_app():
    app = Flask(__name__)


    # ✅ Health check route for Render
    @app.route("/")
    def health_check():
        return "App is running", 200


    # Load configurations and logging settings
    load_configurations(app)
    configure_logging()

    # Import and register blueprints, if any
    app.register_blueprint(webhook_blueprint)

    # Imported here, after views, so the services package is already on
    # sys.path and the web routes share the WhatsApp agent_pool.
    from .web_views import web_blueprint
    app.register_blueprint(web_blueprint)

    return app