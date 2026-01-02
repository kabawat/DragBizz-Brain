def detect_language(text: str) -> str:
    if not text or not isinstance(text, str):
        return "english"
    
    text = text.strip()
    if len(text) < 2:
        return "english"
    
    has_non_ascii = any(ord(char) > 127 for char in text)
    
    if has_non_ascii:
        return "mixed"
    else:
        return "english"

