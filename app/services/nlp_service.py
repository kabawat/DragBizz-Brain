"""
NLP Service
Handles intent recognition and entity extraction using OpenAI GPT-4
"""
import openai
from app.config.settings import settings
from app.utils.logger import logger
from typing import Dict, Any
import json


class NLPService:
    """Natural Language Processing service"""
    
    def __init__(self):
        openai.api_key = settings.OPENAI_API_KEY
        self.model = settings.OPENAI_MODEL
    
    async def recognize_intent(self, transcript: str, language: str = "hinglish") -> Dict[str, Any]:
        """
        Recognize intent and extract entities from transcript
        
        Args:
            transcript: Speech-to-text transcript
            language: Language code
        
        Returns:
            dict: Intent, entities, and confidence
        """
        try:
            logger.info(f"🧠 Processing intent for: {transcript[:50]}...")
            
            # Build prompt based on language
            if language.lower() in ["hi", "hinglish"]:
                prompt = self._build_hindi_prompt(transcript)
            else:
                prompt = self._build_english_prompt(transcript)
            
            # Call OpenAI
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an AI assistant that understands retail management commands in Hindi, English, and Hinglish."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Parse JSON response
            try:
                result = json.loads(result_text)
            except json.JSONDecodeError:
                # Fallback parsing
                result = self._parse_fallback(result_text)
            
            logger.info(f"✅ Intent recognized: {result.get('intent')} (confidence: {result.get('confidence', 0)})")
            return result
            
        except Exception as e:
            logger.error(f"❌ Intent recognition failed: {str(e)}")
            raise Exception(f"Intent recognition failed: {str(e)}")
    
    def _build_english_prompt(self, transcript: str) -> str:
        """Build prompt for English"""
        return f"""
Analyze this voice command and extract the intent and entities:

Command: "{transcript}"

Possible intents:
- create_invoice: Create a new invoice/bill for a customer
- add_stock: Add stock/inventory to a product
- create_bill: Create a supplier bill
- create_customer: Add a new customer
- create_product: Add a new product
- add_expense: Record an expense

Return JSON format:
{{
  "intent": "intent_name",
  "entities": {{
    "productName": "product name if mentioned",
    "quantity": number if mentioned,
    "customerName": "customer name if mentioned",
    "supplierName": "supplier name if mentioned",
    "amount": number if mentioned,
    "category": "category if mentioned"
  }},
  "confidence": 0.0-1.0
}}

Only return valid JSON, no other text.
"""
    
    def _build_hindi_prompt(self, transcript: str) -> str:
        """Build prompt for Hindi/Hinglish"""
        return f"""
Ye voice command analyze karo aur intent aur entities extract karo:

Command: "{transcript}"

Possible intents:
- create_invoice: Customer ko invoice/bill banana
- add_stock: Product mein stock add karna
- create_bill: Supplier ka bill banana
- create_customer: Naya customer add karna
- create_product: Naya product add karna
- add_expense: Expense record karna

JSON format mein return karo:
{{
  "intent": "intent_name",
  "entities": {{
    "productName": "product ka naam agar mention hai",
    "quantity": number agar mention hai,
    "customerName": "customer ka naam agar mention hai",
    "supplierName": "supplier ka naam agar mention hai",
    "amount": number agar mention hai,
    "category": "category agar mention hai"
  }},
  "confidence": 0.0-1.0
}}

Sirf valid JSON return karo, koi aur text nahi.
"""
    
    def _parse_fallback(self, text: str) -> Dict[str, Any]:
        """Fallback parsing if JSON parsing fails"""
        # Simple fallback logic
        text_lower = text.lower()
        
        intent = "unknown"
        if "invoice" in text_lower or "bill" in text_lower:
            intent = "create_invoice"
        elif "stock" in text_lower or "inventory" in text_lower:
            intent = "add_stock"
        elif "supplier" in text_lower:
            intent = "create_bill"
        elif "customer" in text_lower:
            intent = "create_customer"
        elif "product" in text_lower:
            intent = "create_product"
        elif "expense" in text_lower:
            intent = "add_expense"
        
        return {
            "intent": intent,
            "entities": {},
            "confidence": 0.7
        }


# Create service instance
nlp_service = NLPService()
