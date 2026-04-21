import uvicorn
import os
import sys
from pathlib import Path



from personal_os.api.main import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    # SECURITY: Strictly bind to localhost
    uvicorn.run(app, host="127.0.0.1", port=port, reload=False)
