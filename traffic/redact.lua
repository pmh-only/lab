-- Preserve the native request/status/timing fields, but never publish known
-- authentication parameters or bearer file-operation tokens in the report.
local sensitive = {
  token = true, access_token = true, id_token = true, refresh_token = true,
  auth_token = true, authorization = true, api_key = true, apikey = true,
  password = true, passwd = true, client_secret = true, secret = true,
  code = true, state = true, jwt = true, signature = true, sig = true,
  session = true, sessionid = true, session_token = true, md5 = true,
  ["x-amz-signature"] = true, ["x-amz-security-token"] = true,
  ["x-amz-credential"] = true,
}

local file_routes = {
  "files", "zip", "upload-api", "upload-aj", "update-api", "update-aj",
  "upload-blks-api", "upload-blks-aj", "update-blks-api", "update-blks-aj",
}

function redact_auth(tag, timestamp, record)
  if type(record["log"]) ~= "string" then return 0, timestamp, record end
  local line = record["log"]
  line = line:gsub("([?&])([^=&#%s\"]+)=([^&#%s\"]*)", function(prefix, key, value)
    local normalized = key:gsub("%%(%x%x)", function(hex)
      return string.char(tonumber(hex, 16))
    end)
    normalized = normalized:lower()
    if sensitive[normalized] then return prefix .. key .. "=REDACTED" end
    return prefix .. key .. "=" .. value
  end)
  for _, route in ipairs(file_routes) do
    local escaped = route:gsub("%-", "%%-")
    line = line:gsub("(/seafhttp/" .. escaped .. "/)[^/%s?\"#]+", "%1REDACTED")
  end
  line = line:gsub("(/api/tokens/)[^/%s?\"#]+", "%1REDACTED")
  line = line:gsub("(/api/token/)[^/%s?\"#]+", "%1REDACTED")
  record["log"] = line
  return 2, timestamp, record
end
