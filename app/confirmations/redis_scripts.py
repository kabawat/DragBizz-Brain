_CLAIM_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return 'ERR:NOT_FOUND'
end
local payload = cjson.decode(raw)
local now = tonumber(ARGV[1])
if now >= tonumber(payload['expires_at']) then
  redis.call('DEL', KEYS[1])
  return 'ERR:EXPIRED'
end
if payload['user_id'] ~= ARGV[2] or payload['store_id'] ~= ARGV[3]
   or payload['session_id'] ~= ARGV[4] then
  return 'ERR:FORBIDDEN'
end
if ARGV[5] ~= '' and payload['draft_id'] ~= ARGV[5] then
  return 'ERR:DRAFT_MISMATCH'
end
local status = payload['status'] or 'PENDING'
if status == 'SUCCEEDED' or status == 'REJECTED' or status == 'FAILED'
   or status == 'EXECUTING' then
  return 'ERR:ALREADY_USED'
end
local key = ARGV[6]
if key ~= '' then
  payload['business_idempotency_key'] = key
elseif not payload['business_idempotency_key']
   or payload['business_idempotency_key'] == '' then
  return 'ERR:MISSING_KEY'
end
payload['status'] = 'EXECUTING'
local remaining = math.max(1, math.floor(tonumber(payload['expires_at']) - now))
redis.call('SET', KEYS[1], cjson.encode(payload), 'EX', remaining)
return 'OK:' .. cjson.encode(payload)
"""

_COMPLETE_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return 'ERR:NOT_FOUND'
end
local payload = cjson.decode(raw)
payload['status'] = ARGV[1]
local now = tonumber(ARGV[2])
local remaining = math.max(1, math.floor(tonumber(payload['expires_at']) - now))
redis.call('SET', KEYS[1], cjson.encode(payload), 'EX', remaining)
return 'OK:' .. cjson.encode(payload)
"""

