"""Dynamic model manager for handling model availability and limits."""
import json
import logging
import asyncio
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

MODELS_FILE = Path(__file__).resolve().parent.parent.parent / "app" / "data" / "available_models.json"
_file_lock = asyncio.Lock()


async def get_available_models() -> List[str]:
    """Get list of available models from file."""
    async with _file_lock:
        try:
            if not MODELS_FILE.exists():
                logger.warning(f"Models file not found: {MODELS_FILE}, creating with default models")
                default_models = ["allenai/molmo-2-8b:free"]
                await save_models(default_models)
                return default_models
            
            def read_file():
                with open(MODELS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            
            models = await asyncio.to_thread(read_file)
            
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
            models = await get_available_models()
            
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
        MODELS_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        def write_file():
            with open(MODELS_FILE, 'w', encoding='utf-8') as f:
                json.dump(models, f, indent=2, ensure_ascii=False)
        
        await asyncio.to_thread(write_file)
        logger.debug(f"Saved {len(models)} models to file")
    except Exception as e:
        logger.error(f"Error saving models file: {str(e)}", exc_info=True)

