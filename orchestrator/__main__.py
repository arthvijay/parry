from pathlib import Path

import uvicorn
from dotenv import load_dotenv

if __name__ == "__main__":
    load_dotenv(Path(__file__).with_name(".env"), override=False)
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)  # repo root
    uvicorn.run("orchestrator.app:app", host="127.0.0.1", port=8765)
