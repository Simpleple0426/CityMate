"""All keys carry one hash tag. Scripts never call external services."""

VERIFY_CODE = """
if redis.call('HEXISTS', KEYS[1], 'code') == 0 then return 0 end
local n = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
if n > 5 then return 0 end
if redis.call('HGET', KEYS[1], 'phone') ~= ARGV[1] then return 0 end
if redis.call('HGET', KEYS[1], 'code') ~= ARGV[2] then return 0 end
redis.call('HDEL', KEYS[1], 'code', 'phone', 'attempts')
return 1
"""

RESERVE = """
local existing = redis.call('HGET', KEYS[2], ARGV[1])
if existing then return {'existing', existing} end
local stock = redis.call('GET', KEYS[1])
if not stock then return {'unavailable', ''} end
if tonumber(stock) <= 0 then return {'sold_out', ''} end
local t = redis.call('TIME')
if tonumber(t[1]) < tonumber(ARGV[4]) or tonumber(t[1]) >= tonumber(ARGV[5]) then
  return {'closed', ''}
end
redis.call('DECR', KEYS[1])
redis.call('HSET', KEYS[2], ARGV[1], ARGV[2])
redis.call('HSET', KEYS[3], 'status', 'processing', 'user_id', ARGV[1], 'voucher_id', ARGV[3])
redis.call('XADD', KEYS[4], '*', 'order_id', ARGV[2], 'user_id', ARGV[1], 'voucher_id', ARGV[3])
return {'accepted', ARGV[2]}
"""

ORDER_EVENT = """
if redis.call('EXISTS', KEYS[4]) == 1 then return 0 end
local previous = redis.call('HGET', KEYS[3], 'status')
if ARGV[3] ~= 'ready' then
  if redis.call('HGET', KEYS[2], ARGV[1]) == ARGV[2] then
    redis.call('HDEL', KEYS[2], ARGV[1])
    if redis.call('EXISTS', KEYS[1]) == 1 then redis.call('INCR', KEYS[1]) end
  end
end
if not (ARGV[3] == 'ready' and (previous == 'cancelled' or previous == 'rejected')) then
  redis.call('HSET', KEYS[3], 'status', ARGV[3], 'user_id', ARGV[1], 'voucher_id', ARGV[4])
end
redis.call('SET', KEYS[4], '1')
return 1
"""
