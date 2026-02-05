from typing import Optional, List, Any
import base64
import logging
import asyncio
from fastapi import HTTPException

from app.models.product import ProductExtractResponse, ProductPayload
from app.utils.ai import AIClient, parse_json_response
from app.utils.ai.model_manager import get_available_vision_models
from app.constants.ai import EXTRACTION_TEMPERATURE, EXTRACTION_MAX_TOKENS

logger = logging.getLogger(__name__)


class ProductExtractService:
    def __init__(self):
        self.ai_client = AIClient()
        self._vision_models_cache: Optional[List[str]] = None
        self._vision_cache_lock = asyncio.Lock()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
    
    async def _get_vision_models(self) -> List[str]:
        """Get current list of available vision models."""
        async with self._vision_cache_lock:
            if self._vision_models_cache is None:
                self._vision_models_cache = await get_available_vision_models()
            return self._vision_models_cache.copy()
    
    async def _refresh_vision_models(self) -> List[str]:
        """Refresh vision models list from file."""
        async with self._vision_cache_lock:
            self._vision_models_cache = await get_available_vision_models()
            return self._vision_models_cache.copy()
    
    def _encode_image_to_base64(self, image_bytes: bytes) -> str:
        """Encode image bytes to base64 string."""
        return base64.b64encode(image_bytes).decode('utf-8')
    
    def _detect_image_mime_type(self, image_bytes: bytes) -> str:
        if image_bytes.startswith(b'\xff\xd8\xff'):
            return "image/jpeg"
        elif image_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
            return "image/png"
        elif image_bytes.startswith(b'GIF87a') or image_bytes.startswith(b'GIF89a'):
            return "image/gif"
        elif image_bytes.startswith(b'RIFF') and b'WEBP' in image_bytes[:12]:
            return "image/webp"
        else:
            return "image/jpeg"
    
    def _get_vision_prompt(self) -> str:
        """Build the vision extraction prompt for product data."""
        prompt = """Extract product information from this image. Return JSON only with the following structure:

{
  "name": "Product Name",
  "mrp": 0.0,
  "sellingPrice": 0.0,
  "brand": "Brand Name or null",
  "subcategory": "subcategory_id or null",
  "basePrice": 0.0 or null,
  "discount": 0.0 or null,
  "currency": "INR",
  "uom": "PCS or null",
  "barcode": "barcode or null",
  "sku": "SKU code or null",
  "isGstIncluded": true or false,
  "gstInfo": {
    "isGstApplicable": true or false,
    "gstRate": 0.0 or null,
    "gstType": "CGST_SGST or null",
    "hsnCode": "HSN code or null",
    "sacCode": "SAC code or null",
    "cessRate": 0.0
  } or null,
  "content": {
    "shortDescription": "Short description or null",
    "longDescription": "Long description or null",
    "tags": ["tag1", "tag2"] or [],
    "features": ["feature1", "feature2"] or [],
    "specifications": [
      {
        "name": "Spec Name",
        "value": "Spec Value",
        "unit": "Unit or null"
      }
    ] or []
  } or null
}

Rules:
1. Extract ALL visible information from the image (text, prices, descriptions, specifications, etc.)
2. Try to extract store ID and category ID from image if visible, otherwise use null
3. Extract prices (MRP, selling price, base price) as numbers
4. Extract product name, brand, description from visible text
5. Extract specifications, features, tags from product details visible in image
6. Extract GST information if visible (HSN code, GST rate, etc.)
7. Extract barcode if visible
8. For missing fields, use null (not empty string)
9. Return ONLY valid JSON, no markdown, no explanations"""
        
        return prompt
    
    async def extract_product_data(
        self, 
        image_bytes: bytes,
        request: Optional[Any] = None
    ) -> ProductExtractResponse:
        try:
            if not image_bytes or len(image_bytes) == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Image bytes are empty. Please provide a valid image."
                )
            
            try:
                base64_image = self._encode_image_to_base64(image_bytes)
            except Exception as e:
                logger.error(f"Error encoding image to base64: {str(e)}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail="Failed to process image. Please ensure the image is valid."
                )
            
            image_mime_type = self._detect_image_mime_type(image_bytes)
            logger.debug(f"Detected image MIME type: {image_mime_type}")
            
            prompt = self._get_vision_prompt()
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{image_mime_type};base64,{base64_image}"
                            }
                        }
                    ]
                }
            ]
            
            vision_models = await self._get_vision_models()
            
            if not vision_models:
                logger.error("No vision models available in vision_models.json")
                raise HTTPException(
                    status_code=503,
                    detail="No vision models available. Please check vision_models.json file."
                )
            
            logger.info(f"Extracting product data from image using vision AI. Available models: {len(vision_models)}, Image size: {len(image_bytes) / 1024:.2f}KB")
            
            ai_response = await self.ai_client.call_with_fallback(
                messages=messages,
                temperature=EXTRACTION_TEMPERATURE,
                max_tokens=EXTRACTION_MAX_TOKENS * 2,
                use_cache=False,
                response_format={"type": "json_object"},
                models=vision_models,
                is_vision=True
            )
            
            await self._refresh_vision_models()
            
            if not ai_response:
                logger.error("AI service returned no response after trying all vision models")
                raise HTTPException(
                    status_code=503,
                    detail="AI service temporarily unavailable. All vision models failed. Please try again later."
                )
            
            try:
                extracted_data = parse_json_response(ai_response)
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error parsing AI response: {str(e)}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail="Failed to parse AI response. Please try again with a clearer image."
                )
            
            try:
                # Allow partial extraction: do NOT fail request if some fields are missing.
                missing_fields: list[str] = []

                name = extracted_data.get("name")
                if not name or str(name).strip() in ["", "null"]:
                    extracted_data["name"] = None
                    missing_fields.append("name")

                selling_price_raw = extracted_data.get("sellingPrice")
                mrp_raw = extracted_data.get("mrp")

                def _is_missing_price(v) -> bool:
                    return v is None or v == "" or v == "null" or v == 0

                selling_missing = _is_missing_price(selling_price_raw)
                mrp_missing = _is_missing_price(mrp_raw)

                if selling_missing:
                    extracted_data["sellingPrice"] = None
                    missing_fields.append("sellingPrice")
                if mrp_missing:
                    extracted_data["mrp"] = None
                    missing_fields.append("mrp")

                # If only one price is present, use it as the other (best-effort)
                if (not selling_missing) and mrp_missing:
                    extracted_data["mrp"] = selling_price_raw
                    missing_fields = [f for f in missing_fields if f != "mrp"]
                if (not mrp_missing) and selling_missing:
                    extracted_data["sellingPrice"] = mrp_raw
                    missing_fields = [f for f in missing_fields if f != "sellingPrice"]

                # Normalize numeric prices if present (don't hard-fail; just null them if invalid)
                for key in ["mrp", "sellingPrice", "basePrice", "discount"]:
                    val = extracted_data.get(key)
                    if val is None or val == "" or val == "null":
                        extracted_data[key] = None
                        continue
                    try:
                        fval = float(val)
                        if fval < 0:
                            extracted_data[key] = None
                        else:
                            extracted_data[key] = fval
                    except (ValueError, TypeError):
                        extracted_data[key] = None
                
                if extracted_data.get("store") in [None, "", "null"]:
                    extracted_data["store"] = None
                if extracted_data.get("category") in [None, "", "null"]:
                    extracted_data["category"] = None
                
                gst_info = extracted_data.get("gstInfo")
                if gst_info in [None, "", "null"] or not isinstance(gst_info, dict):
                    gst_info = None
                
                if isinstance(gst_info, dict) and (gst_info.get("gstRate") is None or gst_info.get("gstRate") == 0):
                    if extracted_data.get("gstRate") is not None and extracted_data.get("gstRate") != 0:
                        gst_info["gstRate"] = float(extracted_data.get("gstRate"))
                        logger.info(f"GST Rate found at top level, moving to gstInfo: {gst_info['gstRate']}")
                
                if isinstance(gst_info, dict) and gst_info.get("gstRate") is not None:
                    try:
                        gst_info["gstRate"] = float(gst_info["gstRate"])
                        if gst_info["gstRate"] < 0:
                            gst_info["gstRate"] = None
                    except (ValueError, TypeError):
                        gst_info["gstRate"] = None
                
                if isinstance(gst_info, dict) and gst_info.get("isGstApplicable") is None:
                    gst_info["isGstApplicable"] = gst_info.get("gstRate") is not None and gst_info.get("gstRate") > 0
                
                # If gst_info dict is empty after normalization, drop it
                if isinstance(gst_info, dict) and not any(v not in [None, "", "null", 0] for v in gst_info.values()):
                    gst_info = None
                extracted_data["gstInfo"] = gst_info
                
                try:
                    product_payload = ProductPayload(**extracted_data)
                except Exception as e:
                    logger.error(f"Error creating ProductPayload: {str(e)}", exc_info=True)
                    logger.debug(f"Extracted data: {extracted_data}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to validate extracted product data: {str(e)}"
                    )
                
                # If nothing meaningful was extracted, return a user-facing error
                if not product_payload.model_dump(exclude_none=True):
                    raise HTTPException(
                        status_code=400,
                        detail="No product data could be extracted from image. Please try with a clearer image."
                    )

                message = "Product data extracted successfully from image"
                if missing_fields:
                    message = (
                        "Partial product data extracted from image. "
                        f"Missing: {', '.join(sorted(set(missing_fields)))}."
                    )

                return ProductExtractResponse(
                    success=True,
                    payload=product_payload,
                    message=message
                )
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error validating extracted product data: {str(e)}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to validate extracted product data: {str(e)}"
                )
        
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error extracting product data from image: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to extract product data from image: {str(e)}"
            )

