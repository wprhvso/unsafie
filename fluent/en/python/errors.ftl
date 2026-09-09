err-trace = [trace_id=<code>{ $trace_id }</code>]

err-generic = Something went wrong on our side. Please try again
err-empty = The model returned an empty response. Please try again
err-timeout = The answer took too long and was cut off. Try a shorter request
err-storage = Could not save the conversation — the database is unavailable

err-gateway-unreachable = The AI gateway is not responding. Please try again in a minute
err-gateway-auth = The bot is not authorized in the AI gateway
err-gateway-capacity = Every model session is busy or expired. Please try again in a few minutes

err-rate-limit = The model provider is rate limiting us right now. Please try again in a minute
err-upstream-auth = The gateway could not authenticate with the model provider
err-upstream-unavailable = The model provider is temporarily unavailable. Please try again in a few minutes
err-upstream-timeout = The model did not answer in time. Try a shorter request
err-upstream-unreachable = Could not reach the model provider — the network request failed
err-upstream-rejected = The model provider rejected the request as invalid

err-context-length = The conversation is longer than the model can read. Start a new one or send a shorter text
err-content-filter = The model stopped: its safety filters blocked the answer
err-prompt-blocked = The model refused to answer: its safety filters blocked the request
err-model-not-found = The selected model is unavailable. Pick another one: /gemini31 or /gemini3f
err-unsupported-content = This attachment format is not supported

err-retry = 🔄 Retry
err-retry-gone = There is nothing left to retry — send the message again

chat-unsupported = Only text messages are supported

chat-document-unreadable = I could not read that file
