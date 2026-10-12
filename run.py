import logging
import os
from app import create_app



"""

import logging
from app import create_app

# Create the Flask app
app = create_app()

# Optional: Logging config
logging.basicConfig(level=logging.INFO)
logging.info("Flask app loaded")

"""

# Create the Flask app
app = create_app()

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    logging.info("Flask app started")
    
    # Get the PORT from environment variables or default to 5000
    port = int(os.getenv("PORT", 5000))
    
    # Run the app on the assigned port
    app.run(host="0.0.0.0", port=port)

# Render Start Command
# gunicorn "app:create_app()"