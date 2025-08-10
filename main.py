from fastapi import FastAPI
from app.presentation.routers import router
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv ; load_dotenv()

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()   # forces .env load

app = FastAPI(title="MedVerify-AI")
app.include_router(router)

@app.get("/healthz")
async def health():
    return {"ok": True}
