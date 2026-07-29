from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional
from pymongo import MongoClient
from pymongo.errors import PyMongoError
import logging
from bson import ObjectId
import certifi

# =========================
# ЛОГИРОВАНИЕ
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# =========================
# FASTAPI
# =========================
app = FastAPI(
    title="Система автоматизации химического контроля",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# MONGODB
# =========================
try:
    mongo_client = MongoClient(
        "mongodb+srv://gmkolomiets_db_user:YnKyKslvTzHcVqNc@iot.04rdrbv.mongodb.net/?appName=IoT",
    tls=True,
    tlsCAFile=certifi.where(),
    retryWrites=False    )
    db = mongo_client["sens=ors_db"]
    sensor_data_collection = db["sensor_readings"]

    logger.info("Successfully connected to MongoDB")
except PyMongoError as e:
    logger.error(f"MongoDB connection error: {e}")
    raise

# =========================
# MODELS
# =========================
class MongoSensorData(BaseModel):
    _id: str
    date: datetime
    name_of_sensor: str
    value: float

# =========================
# API
# =========================
@app.get("/api/data", response_model=List[MongoSensorData])
async def get_sensor_data(
    name_of_sensor: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = Query(100, gt=0, le=1000)
):
    """
    Получение данных для отображения во фронтенде
    """
    try:
        query = {}

        if name_of_sensor:
            query["name_of_sensor"] = name_of_sensor

        if start_date and end_date:
            query["date"] = {"$gte": start_date, "$lte": end_date}
        elif start_date:
            query["date"] = {"$gte": start_date}
        elif end_date:
            query["date"] = {"$lte": end_date}

        # =========================
        # 🔍 ДИАГНОСТИКА
        # =========================
        logger.info(f"DB: {db.name}, collection: {sensor_data_collection.name}")
        logger.info(f"Collections in DB: {db.list_collection_names()}")
        logger.info(f"Total docs in collection: {sensor_data_collection.estimated_document_count()}")
        logger.info(f"Query: {query}")
        logger.info(f"Matched docs: {sensor_data_collection.count_documents(query)}")

        sample = sensor_data_collection.find_one()
        logger.info(f"Sample doc: {sample}")

        # =========================
        # ОСНОВНОЙ ЗАПРОС
        # =========================
        cursor = (
            sensor_data_collection
            .find(query)
            .sort("date", -1)
            .limit(limit)
        )

        results = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)

        logger.info(f"Returned {len(results)} documents")
        return results

    except PyMongoError as e:
        logger.error(f"MongoDB error: {e}")
        raise HTTPException(status_code=500, detail="MongoDB error")

    except Exception as e:
        logger.exception("Unexpected error")
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# RUN
# =========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
