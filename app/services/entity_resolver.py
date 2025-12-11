"""
Entity Resolver Service
Resolves entity names (product names, customer names) to IDs
"""
import httpx
from app.config.settings import settings
from app.utils.logger import logger
from typing import Dict, Any, Optional


class EntityResolver:
    """Resolves entity names to database IDs"""
    
    def __init__(self):
        self.base_url = settings.RETAILER_SERVICE_URL
    
    async def resolve_entities(
        self,
        entities: Dict[str, Any],
        store_id: str,
        user_token: str
    ) -> Dict[str, Any]:
        """
        Resolve entity names to IDs
        
        Args:
            entities: Raw entities with names
            store_id: Store ID
            user_token: JWT token
        
        Returns:
            dict: Entities with resolved IDs
        """
        resolved = entities.copy()
        
        try:
            # Resolve product name to ID
            if entities.get("productName"):
                product_id = await self._resolve_product(
                    entities["productName"], store_id, user_token
                )
                if product_id:
                    resolved["productId"] = product_id
            
            # Resolve customer name to ID
            if entities.get("customerName"):
                customer_id = await self._resolve_customer(
                    entities["customerName"], store_id, user_token
                )
                if customer_id:
                    resolved["customerId"] = customer_id
            
            # Resolve supplier name to ID
            if entities.get("supplierName"):
                supplier_id = await self._resolve_supplier(
                    entities["supplierName"], store_id, user_token
                )
                if supplier_id:
                    resolved["supplierId"] = supplier_id
            
            # Resolve category name to ID
            if entities.get("category"):
                category_id = await self._resolve_category(
                    entities["category"], store_id, user_token
                )
                if category_id:
                    resolved["categoryId"] = category_id
            
            return resolved
            
        except Exception as e:
            logger.warning(f"⚠️ Entity resolution warning: {str(e)}")
            return resolved
    
    async def _resolve_product(self, product_name: str, store_id: str, token: str) -> Optional[str]:
        """Resolve product name to ID"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/product",
                    params={"store": store_id, "search": product_name, "limit": 1},
                    headers={"Authorization": f"Bearer {token}"}
                )
                if response.status_code == 200:
                    data = response.json()
                    products = data.get("data", {}).get("data", []) or data.get("data", [])
                    if products:
                        return products[0].get("_id") or products[0].get("id")
        except Exception as e:
            logger.warning(f"⚠️ Product resolution failed: {str(e)}")
        return None
    
    async def _resolve_customer(self, customer_name: str, store_id: str, token: str) -> Optional[str]:
        """Resolve customer name to ID"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/customer",
                    params={"store": store_id, "search": customer_name, "limit": 1},
                    headers={"Authorization": f"Bearer {token}"}
                )
                if response.status_code == 200:
                    data = response.json()
                    customers = data.get("data", {}).get("data", []) or data.get("data", [])
                    if customers:
                        return customers[0].get("_id") or customers[0].get("id")
        except Exception as e:
            logger.warning(f"⚠️ Customer resolution failed: {str(e)}")
        return None
    
    async def _resolve_supplier(self, supplier_name: str, store_id: str, token: str) -> Optional[str]:
        """Resolve supplier name to ID"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/supplier",
                    params={"store": store_id, "search": supplier_name, "limit": 1},
                    headers={"Authorization": f"Bearer {token}"}
                )
                if response.status_code == 200:
                    data = response.json()
                    suppliers = data.get("data", {}).get("data", []) or data.get("data", [])
                    if suppliers:
                        return suppliers[0].get("_id") or suppliers[0].get("id")
        except Exception as e:
            logger.warning(f"⚠️ Supplier resolution failed: {str(e)}")
        return None
    
    async def _resolve_category(self, category_name: str, store_id: str, token: str) -> Optional[str]:
        """Resolve category name to ID"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/category",
                    params={"store": store_id, "search": category_name, "limit": 1},
                    headers={"Authorization": f"Bearer {token}"}
                )
                if response.status_code == 200:
                    data = response.json()
                    categories = data.get("data", {}).get("data", []) or data.get("data", [])
                    if categories:
                        return categories[0].get("_id") or categories[0].get("id")
        except Exception as e:
            logger.warning(f"⚠️ Category resolution failed: {str(e)}")
        return None


# Create service instance
entity_resolver = EntityResolver()
