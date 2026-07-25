# Quick Guide (Hinglish)

## Ye docs kyun hain?

Ab **saara AI kaam `dragbizz-ai` mein** hoga.  
`dragbizz-ai-service` se **kya banana hai** (product) liya gaya hai.  
**Kaise banana hai** — is repo ke current flow se:  
`Chat → Guards → RAG → LLM → ToolValidator → ToolExecutor → Retailer`.

## Pehle kya padho

1. [00_VISION_AND_GOLDEN_RULES.md](./00_VISION_AND_GOLDEN_RULES.md) — rules  
2. [01_GAP_ANALYSIS.md](./01_GAP_ANALYSIS.md) — abhi kya missing hai  
3. [03_MASTER_IMPLEMENTATION_PLAN.md](./03_MASTER_IMPLEMENTATION_PLAN.md) — step-by-step plan  

## Sabse pehle implement kya karein

1. **A1** — second LLM turn (tool results se message ground)  
2. **A2** — zyada READ tools (top sellers, low stock, …)  
3. **B1** Redis → **C1** invoice draft + confirm  
4. Phir voice / WhatsApp / image / analytics  

## Yaad rakho

- AI Mongo pe seedha write nahi karega — sirf retailer drafts  
- WRITE tools bina confirm ke release nahi  
- Qdrant RAG rehne do; Postgres baad mein sessions/jobs ke liye  
- LangGraph copy-paste mat karo — `ChatService` extend karo  
