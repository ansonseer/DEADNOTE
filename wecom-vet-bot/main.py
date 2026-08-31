"""生产入口：uvicorn main:app --host 0.0.0.0 --port 8000"""

import logging

from app.config import Settings
from app.server import create_app

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)

app = create_app(Settings.from_env())

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
