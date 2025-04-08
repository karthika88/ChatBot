import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.requests import Request
from app.database import candidates_collection
from app.routes.interview_routes import router as interview_router
from app.resume_selection import router as resume_router
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from app.interview_bridge import monitor_calendar  # 👈 Import the bridge function
from app.routes import telnyx_call
from fastapi.middleware.cors import CORSMiddleware
from app.interview_bridge import fetch_interview_result

app = FastAPI()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Allow CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(interview_router)
app.include_router(resume_router)
app.include_router(telnyx_call.router)
logger.info("✅ Routers mounted successfully")

# Initialize scheduler
scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup_event():
    """Initialize application on startup"""
    try:
        # Start scheduler
        scheduler.start()
        logger.info("✅ Scheduler started successfully")

        # 👉 Start interview monitoring bridge
        scheduler.add_job(
            monitor_calendar,
            trigger='interval',
            seconds=60,
            id='interview_monitor',
            replace_existing=True
        )
        logger.info("✅ Interview monitor scheduled to run every 60 seconds")
        logger.info("🔎 Checking for candidates needing scheduling update...")

        # Update pending candidates with proper async handling
        try:
            filter_query = {
                "status": "Shortlisted", 
                "scheduling_enabled": {"$ne": True}
            }

            candidates_to_update = await candidates_collection.find(filter_query).to_list(length=None)
            logger.info(f"ℹ️ Candidates found: {len(candidates_to_update)}")

            if candidates_to_update:
                update_count = 0
                for candidate in candidates_to_update:
                    result = await candidates_collection.update_one(
                        {"_id": candidate["_id"]},
                        {"$set": {"scheduling_enabled": True}}
                    )
                    if result.modified_count > 0:
                        logger.info(f"✅ Candidate {candidate['_id']} scheduling enabled")
                        update_count += 1
                
                logger.info(f"✅ Updated {update_count} candidates")
            else:
                logger.info("No candidates needed updating")

        except Exception as db_error:
            logger.error(f"❌ Database error: {str(db_error)}")

    except Exception as e:
        logger.error(f"❌ Error during startup: {str(e)}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("🛑 Shutting down FastAPI app...")
    try:
        scheduler.shutdown()
        logger.info("✅ Scheduler shutdown successfully")
    except Exception as e:
        logger.error(f"❌ Error during shutdown: {e}")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serve the main application page"""
    logger.info("📄 Serving main application page")
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
async def health_check():
    """Check application health"""
    logger.info("📊 Running health check...")
    try:
        # Test database connection
        await candidates_collection.find_one({})
        db_status = "connected"
        logger.info("✅ Database connected")
    except Exception:
        db_status = "disconnected"
        logger.warning(f"⚠️ Database connection failed: {e}")

    return {
        "status": "healthy",
        "scheduler_running": scheduler.running,
        "database": db_status
    }

@app.get("/get_interview_result/")
async def get_interview_result(interview_id: str = Query(...)):
    try:
        result = await fetch_interview_result(interview_id)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(content={"error": "An error occurred while processing the request"}, status_code=500)

if __name__ == "__main__":
    logger.info("📦 Running app via Uvicorn")
    # Start the app
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
