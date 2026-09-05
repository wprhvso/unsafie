"""Attribute names in one place, and everything that must never reach a span.

Span *names* stay low-cardinality — anything variable (an id, a repo, a command) is an
attribute. Payloads (prompts, tool arguments, command output) are optional: a trace store is
neither a log nor a place for secrets, so content is off by default, always truncated and
always scrubbed.
"""

import json
import re
from typing import Any

from unsafie.settings import settings

# resource
SERVICE_NAME = "service.name"
SERVICE_VERSION = "service.version"
SERVICE_INSTANCE = "service.instance.id"
ENVIRONMENT = "deployment.environment.name"
HOST_NAME = "host.name"
PROCESS_PID = "process.pid"

# who and where
BOT_ID = "unsafie.bot_id"
CHAT_ID = "unsafie.chat_id"
USER_ID = "unsafie.user_id"
TURN_ID = "unsafie.turn_id"
UPDATE_ID = "unsafie.update_id"
MESSAGE_ID = "unsafie.message_id"
REQUEST_ID = "unsafie.request_id"
LOCALE = "unsafie.locale"

# outcome
REFUSED = "unsafie.refused"
REFUSAL = "unsafie.refusal"
CANCELLED = "unsafie.cancelled"
PARENT_TRACE = "unsafie.parent_trace_id"

# telegram
TG_UPDATE_TYPE = "unsafie.telegram.update_type"
TG_METHOD = "unsafie.telegram.method"
TG_CHUNKS = "unsafie.telegram.chunks"
TG_MESSAGE_IDS = "unsafie.telegram.message_ids"
TG_KIND = "unsafie.telegram.kind"
FILE_NAME = "unsafie.file.name"
FILE_BYTES = "unsafie.file.bytes"
FILE_MEDIA = "unsafie.file.media"
TG_SILENT = "unsafie.telegram.silent"
TG_RETRIES = "unsafie.telegram.retries"

# agent
TOOL = "unsafie.tool"
TOOL_ARGS = "unsafie.tool.args"
TOOL_RESULT = "unsafie.tool.result"
TOOL_ERROR = "unsafie.tool.is_error"
TOOL_SOURCE = "unsafie.tool.source"
ATTEMPT = "unsafie.attempt"
CREDENTIAL_ID = "unsafie.credential.id"
CREDENTIAL_KIND = "unsafie.credential.kind"
FAILURE = "unsafie.failure"
OUTCOME = "unsafie.outcome"
TURN_STATUS = "unsafie.turn.status"
COST_USD = "unsafie.cost_usd"
CHARGE = "unsafie.charge"
BUDGET_USD = "unsafie.budget_usd"
EFFORT = "unsafie.effort"
SERVERS = "unsafie.servers"
RESUME = "unsafie.resume"
FORK = "unsafie.fork"
INJECTED = "unsafie.injected"
PROMPT = "unsafie.prompt"
COMPLETION = "unsafie.completion"
BLOCKS = "unsafie.blocks"
TOOL_CALLS = "unsafie.tool_calls"
SDK_MESSAGES = "unsafie.sdk_messages"
NUM_TURNS = "unsafie.num_turns"

# gen_ai semantic conventions (https://opentelemetry.io/docs/specs/semconv/gen-ai/)
GEN_AI_SYSTEM = "gen_ai.system"
GEN_AI_OPERATION = "gen_ai.operation.name"
GEN_AI_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_CONVERSATION = "gen_ai.conversation.id"
GEN_AI_TOOL_NAME = "gen_ai.tool.name"
GEN_AI_TOOL_CALL_ID = "gen_ai.tool.call.id"
GEN_AI_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_FINISH_REASONS = "gen_ai.response.finish_reasons"

# github
GH_REPO = "unsafie.github.repo"
GH_BRANCH = "unsafie.github.branch"
GH_EVENT = "unsafie.github.event"
GH_DELIVERY = "unsafie.github.delivery_id"
GH_ATTEMPT = "unsafie.github.attempt"
GH_REQUESTS = "unsafie.github.requests"
GH_HITS = "unsafie.github.cache_hits"
GH_BULK = "unsafie.github.from_snapshot"
GH_BYTES = "unsafie.github.bytes"
GH_FILES = "unsafie.github.files"
GH_SHA = "unsafie.github.sha"
GH_NOTIFIED = "unsafie.github.notified"

# ssh
SSH_ALIAS = "unsafie.ssh.alias"
SSH_COMMAND = "unsafie.ssh.command"
SSH_EXIT = "unsafie.ssh.exit_code"
SSH_REUSED = "unsafie.ssh.reused"
SSH_TRUNCATED = "unsafie.ssh.truncated"
SSH_PATH = "unsafie.ssh.path"
SSH_BYTES = "unsafie.ssh.bytes"

# scheduler and loops
LOOP = "unsafie.loop"
TASK_ID = "unsafie.task.id"
TASK_KIND = "unsafie.task.kind"
WATCH_ID = "unsafie.watch.id"
WATCH_NAME = "unsafie.watch.name"
WATCH_FIRES = "unsafie.watch.fires"

# http semconv, used for our hand-written client spans
HTTP_METHOD = "http.request.method"
HTTP_STATUS = "http.response.status_code"
HTTP_URL = "url.full"
HTTP_BODY_SIZE = "http.response.body.size"
SERVER_ADDRESS = "server.address"
SERVER_PORT = "server.port"

SECRETS = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{16,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-ant-[A-Za-z0-9\-_]{16,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"
    r"|(?i:authorization|api[-_]?key|password|token)[\"'\s:=]+[A-Za-z0-9._\-]{8,})"
)


def scrub(value: str) -> str:
    return SECRETS.sub("«redacted»", value)


def stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return repr(value)


def clip(value: Any, limit: int | None = None) -> str:
    """Truncate and scrub. Used for everything that goes into an attribute as text."""
    limit = limit or settings.otel_max_attr_len
    text = scrub(stringify(value))
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…(+{len(text) - limit} chars)"


def content(value: Any, limit: int | None = None) -> str | None:
    """A payload attribute: None (and therefore dropped) unless content capture is on."""
    if value is None or not settings.otel_capture_content:
        return None
    return clip(value, limit)
