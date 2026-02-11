AI_BASE_URL = "https://openrouter.ai/api/v1"
AI_CHAT_ENDPOINT = "/chat/completions"

DEFAULT_TEMPERATURE = 0.3
EXTRACTION_TEMPERATURE = 0.1
DEFAULT_MAX_TOKENS = 150
EXTRACTION_MAX_TOKENS = 1000

CONVERSATION_PROMPT_BASE = "Voice AI. Ask missing customer details. Same language. Brief (1-2 sentences). Text only."
LANGUAGE_INSTRUCTION = "CRITICAL: Always respond in the EXACT same language, script, and style as the user's query. Match the user's language perfectly - if they write in Hindi, respond in Hindi; if Gujarati, respond in Gujarati; if English, respond in English. Use the same script (Devanagari, Gujarati, Tamil, etc.) as the user."

EXTRACTION_SYSTEM_PROMPT = """Extract customer data. Return JSON only.

Schema:{"name":str|null,"phone":str|null,"email":str|null,"store":str|null,"companyDetails":{"gstin":str|null,"companyName":str|null}|null,"addresses":{"billing":{"addressLine1","city","state","pincode","country","label":str|null}|null,"shipping":{"addressLine1","city","state","pincode","country","label":str|null}|null},"extractedFields":["field1"]}

Rules: Extract only mentioned data. Missing=null. JSON only."""

