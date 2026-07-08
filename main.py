from __future__ import annotations

import uvicorn

from app.config import get_config

if __name__ == "__main__":
    config = get_config()
    uvicorn.run("app.main:app", host="0.0.0.0", port=config.web_port)
