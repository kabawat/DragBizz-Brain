"""
API Client Service
Calls retailer service APIs with transformed payloads
"""
import httpx
from app.config.settings import settings
from app.utils.logger import logger
from typing import Dict, Any, Optional
from app.services.entity_resolver import EntityResolver


class APIClient:
    """API client for retailer service"""
    
    def __init__(self):
        self.base_url = settings.RETAILER_SERVICE_URL
        self.entity_resolver = EntityResolver()
    
    async def execute_command(
        self,
        intent: str,
        entities: Dict[str, Any],
        user_token: str,
        store_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """
        Execute voice command by calling appropriate retailer API
        
        Args:
            intent: Command intent
            entities: Extracted entities
            user_token: JWT token
            store_id: Store ID
            user_id: User ID
        
        Returns:
            dict: API response
        """
        try:
            logger.info(f"📡 Executing command: {intent}")
            
            # Resolve entities (names to IDs)
            resolved_entities = await self.entity_resolver.resolve_entities(
                entities, store_id, user_token
            )
            
            # Build API payload based on intent
            payload = self._build_payload(intent, resolved_entities, store_id)
            
            # Get API endpoint
            endpoint = self._get_endpoint(intent)
            
            # Make API call
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}{endpoint}",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {user_token}",
                        "Content-Type": "application/json"
                    }
                )
                
                response.raise_for_status()
                result = response.json()
                
                logger.info(f"✅ API call successful: {intent}")
                return {
                    "success": True,
                    "data": result.get("data") or result,
                    "message": result.get("message", "Command executed successfully")
                }
                
        except httpx.HTTPStatusError as e:
            error_data = e.response.json() if e.response else {}
            logger.error(f"❌ API call failed: {e.response.status_code} - {error_data}")
            return {
                "success": False,
                "error": error_data,
                "message": error_data.get("message", "API call failed")
            }
        except Exception as e:
            logger.error(f"❌ API call error: {str(e)}")
            return {
                "success": False,
                "error": {"message": str(e)},
                "message": "Failed to execute command"
            }
    
    def _get_endpoint(self, intent: str) -> str:
        """Get API endpoint for intent"""
        endpoint_map = {
            "create_invoice": "/invoices",
            "add_stock": "/stock",
            "create_bill": "/supplier-account/bills",
            "create_customer": "/customer",
            "create_product": "/product",
            "add_expense": "/expense"
        }
        return endpoint_map.get(intent, "/invoices")
    
    def _build_payload(self, intent: str, entities: Dict[str, Any], store_id: str) -> Dict[str, Any]:
        """Build API payload from entities"""
        payload = {"store": store_id}
        
        if intent == "create_invoice":
            payload.update({
                "customer": entities.get("customerId"),
                "items": [
                    {
                        "product": entities.get("productId"),
                        "quantity": entities.get("quantity", 1)
                    }
                ],
                "totalDiscount": entities.get("discount", 0)
            })
        
        elif intent == "add_stock":
            payload.update({
                "productId": entities.get("productId"),
                "batchData": {
                    "quantity": entities.get("quantity", 1),
                    "purchasePrice": entities.get("amount", 0),
                    "supplier": entities.get("supplierId")
                }
            })
        
        elif intent == "create_bill":
            payload.update({
                "supplier": entities.get("supplierId"),
                "items": [
                    {
                        "product": entities.get("productId"),
                        "quantity": entities.get("quantity", 1),
                        "purchasePrice": entities.get("amount", 0)
                    }
                ]
            })
        
        elif intent == "create_customer":
            payload.update({
                "name": entities.get("customerName"),
                "phone": entities.get("phone"),
                "email": entities.get("email")
            })
        
        elif intent == "create_product":
            payload.update({
                "name": entities.get("productName"),
                "category": entities.get("categoryId"),
                "mrp": entities.get("amount", 0),
                "sellingPrice": entities.get("amount", 0)
            })
        
        elif intent == "add_expense":
            payload.update({
                "amount": entities.get("amount", 0),
                "description": entities.get("description", ""),
                "category": entities.get("category")
            })
        
        # Remove None values
        return {k: v for k, v in payload.items() if v is not None}


# Create service instance
api_client = APIClient()
