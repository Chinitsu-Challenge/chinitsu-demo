import uvicorn
logging_config = uvicorn.config.LOGGING_CONFIG

logging_config["loggers"]["game_log"] = {
    "handlers": ["default"],
    "level": "INFO",
    "propagate": False,
}
logging_config["handlers"]["game_log"] = {
    "formatter": "default",
    "class": "logging.StreamHandler",
    "stream": "ext://sys.stderr",
}

if __name__ == "__main__":
    from app import app
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=logging_config)