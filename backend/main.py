from fastapi import FastAPI

app = FastAPI(
    title="MarketScoutAI API",
    description="Autonomous Web Research & Market Intelligence Agent",
    version="0.1.0",
)


@app.get("/")
def root():
    return {
        "message": "MarketScoutAI API is running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }