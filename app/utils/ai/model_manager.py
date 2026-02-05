"""Dynamic model manager for handling model availability and limits."""
import json
import logging
import asyncio
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# NOTE: `model_manager.py` lives in `app/utils/ai/`.
# We want the models under `app/data/` (not `app/app/data/`).
_APP_ROOT = Path(__file__).resolve().parents[2]  # .../app
MODELS_FILE = _APP_ROOT / "data" / "available_models.json"
VISION_MODELS_FILE = _APP_ROOT / "data" / "vision_models.json"
_file_lock = asyncio.Lock()
_vision_file_lock = asyncio.Lock()

def _read_json_list(path: Path) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json_list(path: Path, data: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


async def get_available_models() -> List[str]:
    """Get list of available models from file."""
    async with _file_lock:
        try:
            if not MODELS_FILE.exists():
                logger.warning(f"Models file not found: {MODELS_FILE}, creating with default models")
                default_models = ["allenai/molmo-2-8b:free"]
                await save_models(default_models)
                return default_models

            models = await asyncio.to_thread(_read_json_list, MODELS_FILE)
            
            if not isinstance(models, list) or len(models) == 0:
                logger.warning("Models file is empty or invalid, using default model")
                return ["allenai/molmo-2-8b:free"]
            
            return models
        except Exception as e:
            logger.error(f"Error reading models file: {str(e)}", exc_info=True)
            return ["allenai/molmo-2-8b:free"]


async def remove_model(model: str) -> bool:
    """Remove a model from the available models list when limit is reached."""
    async with _file_lock:
        try:
            # IMPORTANT: don't call get_available_models() while holding _file_lock
            # (get_available_models itself acquires _file_lock → deadlock).
            if not MODELS_FILE.exists():
                models: list[str] = ["allenai/molmo-2-8b:free"]
            else:
                loaded = await asyncio.to_thread(_read_json_list, MODELS_FILE)
                models = loaded if isinstance(loaded, list) else []
            
            if model not in models:
                logger.debug(f"Model {model} not in list, skipping removal")
                return False
            
            models.remove(model)
            
            if len(models) == 0:
                logger.error("All models exhausted! Adding default model as fallback")
                models = ["allenai/molmo-2-8b:free"]
            
            await save_models(models)
            logger.info(f"Removed model {model} from available models. Remaining: {len(models)}")
            return True
        except Exception as e:
            logger.error(f"Error removing model {model}: {str(e)}", exc_info=True)
            return False


async def save_models(models: List[str]) -> None:
    """Save models list to file."""
    try:
        await asyncio.to_thread(_write_json_list, MODELS_FILE, models)
        logger.debug(f"Saved {len(models)} models to file")
    except Exception as e:
        logger.error(f"Error saving models file: {str(e)}", exc_info=True)


# Vision Models Management
async def get_available_vision_models() -> List[str]:
    """Get list of available vision models from file."""
    async with _vision_file_lock:
        try:
            if not VISION_MODELS_FILE.exists():
                logger.warning(f"Vision models file not found: {VISION_MODELS_FILE}, creating with default vision models")
                default_vision_models = [
                    "allenai/molmo-2-8b:free",
                    "nvidia/nemotron-nano-12b-v2-vl:free",
                    "mistralai/mistral-small-3.1-24b-instruct:free",
                    "google/gemma-3-4b-it:free",
                    "google/gemma-3-12b-it:free",
                    "google/gemma-3-27b-it:free",
                    "google/gemini-2.0-flash-exp:free",
                    "qwen/qwen-2.5-vl-7b-instruct:free",
                ]
                await save_vision_models(default_vision_models)
                return default_vision_models

            models = await asyncio.to_thread(_read_json_list, VISION_MODELS_FILE)
            
            if not isinstance(models, list) or len(models) == 0:
                logger.warning("Vision models file is empty or invalid, using default vision models")
                default_vision_models = [
                    "allenai/molmo-2-8b:free",
                    "nvidia/nemotron-nano-12b-v2-vl:free",
                    "mistralai/mistral-small-3.1-24b-instruct:free",
                    "google/gemma-3-4b-it:free",
                    "google/gemma-3-12b-it:free",
                    "google/gemma-3-27b-it:free",
                    "google/gemini-2.0-flash-exp:free",
                    "qwen/qwen-2.5-vl-7b-instruct:free",
                ]
                return default_vision_models
            
            return models
        except Exception as e:
            logger.error(f"Error reading vision models file: {str(e)}", exc_info=True)
            return [
                "allenai/molmo-2-8b:free",
                "nvidia/nemotron-nano-12b-v2-vl:free",
                "mistralai/mistral-small-3.1-24b-instruct:free",
                "google/gemma-3-4b-it:free",
                "google/gemma-3-12b-it:free",
                "google/gemma-3-27b-it:free",
                "google/gemini-2.0-flash-exp:free",
                "qwen/qwen-2.5-vl-7b-instruct:free",
            ]


async def remove_vision_model(model: str) -> bool:
    """Remove a vision model from the available vision models list when limit is reached."""
    async with _vision_file_lock:
        try:
            # Same deadlock avoidance as remove_model()
            if not VISION_MODELS_FILE.exists():
                models: list[str] = ["allenai/molmo-2-8b:free"]
            else:
                loaded = await asyncio.to_thread(_read_json_list, VISION_MODELS_FILE)
                models = loaded if isinstance(loaded, list) else []
            
            if model not in models:
                logger.debug(f"Vision model {model} not in list, skipping removal")
                return False
            
            models.remove(model)
            
            if len(models) == 0:
                logger.error("All vision models exhausted! Adding default vision model as fallback")
                models = ["allenai/molmo-2-8b:free"]
            
            await save_vision_models(models)
            logger.info(f"Removed vision model {model} from available vision models. Remaining: {len(models)}")
            return True
        except Exception as e:
            logger.error(f"Error removing vision model {model}: {str(e)}", exc_info=True)
            return False


async def save_vision_models(models: List[str]) -> None:
    """Save vision models list to file."""
    try:
        await asyncio.to_thread(_write_json_list, VISION_MODELS_FILE, models)
        logger.debug(f"Saved {len(models)} vision models to file")
    except Exception as e:
        logger.error(f"Error saving vision models file: {str(e)}", exc_info=True)

