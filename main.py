from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import asyncio
from script import process_wallet, clear_cache
import aiohttp

app = FastAPI()

class WalletRequest(BaseModel):
    wallets: List[str]

@app.post("/check")
async def check_wallets(request: WalletRequest):
    try:
        # Bersihkan cache di awal
        clear_cache()
        
        # Validasi alamat dompet
        invalid_wallets = [w for w in request.wallets if not w.startswith("0x") or len(w) != 42]
        if invalid_wallets:
            raise HTTPException(status_code=400, detail=f"Invalid wallet addresses: {invalid_wallets}")
        
        # Proses setiap dompet
        results = []
        async with aiohttp.ClientSession() as session:
            for wallet in request.wallets:
                # Tangkap output konsol
                from io import StringIO
                import sys
                old_stdout = sys.stdout
                sys.stdout = StringIO()
                
                try:
                    await process_wallet(wallet, session)
                    output = sys.stdout.getvalue()
                    results.append({"wallet": wallet, "output": output})
                finally:
                    sys.stdout = old_stdout
        
        return {"status": "success", "results": results}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    return {"message": "Wallet Checker API. Use POST /check with a list of wallet addresses."}
