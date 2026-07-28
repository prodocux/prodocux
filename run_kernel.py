"""Start the ProDocuX Kernel service.

Usage: python run_kernel.py
Listens on http://localhost:8900
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="127.0.0.1", port=8900, reload=False)
