"""Start the server:  python run.py"""

import logging
import os

from unifit.app import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

# The reminder scheduler runs inside this process, so run a single instance.
app = create_app(start_scheduler=True)

if __name__ == "__main__":
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "5000")),
            debug=False, use_reloader=False)
