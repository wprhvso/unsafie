const CALL_BLOCKS = ['tool_use', 'server_tool_use'];
const THINK_BLOCKS = ['thinking', 'redacted_thinking'];

const USAGE = [
  'input_tokens',
  'output_tokens',
  'cache_read_input_tokens',
  'cache_creation_input_tokens'
];

function merge(into, usage) {
  for (const key of USAGE) {
    const value = usage?.[key];
    if (typeof value === 'number') into[key] = (into[key] ?? 0) + value;
  }
}

export function timeline() {
  const state = $state({
    items: [],
    turn: null,
    model: null,
    effort: null,
    display: null,
    thinking: null,
    steps: 0,
    calls: 0,
    cost: 0,
    charge: 0,
    usage: {},
    startedAt: null,
    endedAt: null,
    outcome: null
  });

  let blocks = new Map();
  let calls = new Map();
  let steps = new Map();
  let attempts = [];

  const at = (frame) => frame.at ?? null;
  const key = (data) => `${data.step ?? 0}:${data.index ?? 0}`;

  function push(item) {
    state.items.push(item);
    return state.items[state.items.length - 1];
  }

  function opened(id, when, data) {
    const kind = data.type;
    const base = {
      id,
      at: when,
      step: data.step ?? 0,
      index: data.index ?? 0,
      streaming: true
    };
    let item;
    if (CALL_BLOCKS.includes(kind)) {
      item = {
        ...base,
        type: 'tool',
        name: data.name ?? '?',
        callId: data.id ?? null,
        server: kind === 'server_tool_use',
        args: '',
        input: null,
        output: null,
        ok: null,
        ms: null,
        phase: 'writing'
      };
      state.calls += 1;
    } else if (THINK_BLOCKS.includes(kind)) {
      item = { ...base, type: 'think', text: '', redacted: kind === 'redacted_thinking' };
    } else if (kind === 'text' || !kind) {
      item = { ...base, type: 'text', text: '' };
    } else {
      item = { ...base, type: 'raw', name: kind, block: data.block ?? null };
    }
    const stored = push(item);
    blocks.set(key(data), stored);
    if (stored.callId) calls.set(stored.callId, stored);
    return stored;
  }

  function grow(data, field) {
    const item = blocks.get(key(data));
    if (!item) return;
    item[field] = (item[field] ?? '') + (data.text ?? '');
    if (data.cut) item.cut = (item.cut ?? 0) + data.cut;
  }

  function apply(frame) {
    const data = frame.data ?? {};
    const when = at(frame);
    switch (frame.kind) {
      case 'turn.start':
        state.turn = { id: data.turn_id, chat: data.chat_id, resumed: data.resumed ?? 0 };
        state.startedAt = when;
        push({ id: frame.id, at: when, type: 'prompt', text: data.prompt ?? '' });
        break;

      case 'attempt.start': {
        state.model = data.model ?? state.model;
        state.effort = data.effort ?? state.effort;
        state.display = data.display ?? state.display;
        state.thinking = data.thinking ?? state.thinking;
        const item = push({
          id: frame.id,
          at: when,
          type: 'attempt',
          attempt: data.attempt,
          model: data.model,
          effort: data.effort,
          budget: data.budget_usd,
          tools: data.tools,
          servers: data.servers ?? [],
          thinking: data.thinking,
          display: data.display
        });
        attempts.push(item);
        break;
      }

      case 'attempt.end': {
        const item = attempts[attempts.length - 1];
        if (item) {
          item.status = data.status;
          item.cost = data.cost_usd;
          item.stop = data.stop_reason;
          item.error = data.error;
        }
        state.cost += data.cost_usd ?? 0;
        state.charge += data.charge ?? 0;
        break;
      }

      case 'step.start': {
        state.steps = Math.max(state.steps, data.step ?? 0);
        const item = push({
          id: frame.id,
          at: when,
          type: 'step',
          step: data.step,
          messages: data.messages,
          tools: data.tools
        });
        steps.set(data.step, item);
        break;
      }

      case 'step.model': {
        const item = steps.get(data.step);
        if (item) item.model = data.model;
        break;
      }

      case 'step.end': {
        const item = steps.get(data.step);
        if (item) {
          item.model = data.model ?? item.model;
          item.stop = data.stop_reason;
          item.usage = data.usage ?? {};
          item.endedAt = when;
        }
        merge(state.usage, data.usage);
        (data.blocks ?? []).forEach((block, index) => {
          const target = blocks.get(`${data.step}:${index}`);
          if (!target) return;
          if (block.hidden) target.hidden = true;
          if (typeof block.chars === 'number') target.chars = block.chars;
        });
        break;
      }

      case 'block.open':
        opened(frame.id, when, data);
        break;

      case 'block.text':
      case 'block.think':
        grow(data, 'text');
        break;

      case 'block.args':
        grow(data, 'args');
        break;

      case 'block.close': {
        const item = blocks.get(key(data));
        if (item) {
          item.streaming = false;
          if (item.type === 'tool' && item.phase === 'writing') item.phase = 'ready';
        }
        break;
      }

      case 'tool.start': {
        const item = calls.get(data.call_id);
        if (item) {
          item.input = data.input ?? {};
          item.phase = 'running';
          item.startedAt = when;
        }
        break;
      }

      case 'tool.end': {
        const item = calls.get(data.call_id);
        if (!item) break;
        item.output = data.output ?? [];
        item.ok = data.ok !== false;
        item.ms = data.ms;
        item.phase = 'done';
        break;
      }

      case 'reply.sent':
        push({
          id: frame.id,
          at: when,
          type: 'reply',
          text: data.text ?? '',
          kind: data.kind,
          messageIds: data.message_ids ?? []
        });
        break;

      case 'note':
        push({ id: frame.id, at: when, type: 'note', name: data.name, attributes: data.attributes });
        break;

      case 'error':
        push({ id: frame.id, at: when, type: 'error', message: data.message, errorType: data.type });
        break;

      case 'turn.end':
        state.endedAt = when;
        state.outcome = data.status;
        if (typeof data.cost_usd === 'number') state.cost = data.cost_usd;
        if (typeof data.charge === 'number') state.charge = data.charge;
        push({
          id: frame.id,
          at: when,
          type: 'end',
          status: data.status,
          steps: data.steps,
          cost: data.cost_usd,
          charge: data.charge,
          note: data.note
        });
        break;

      default:
        break;
    }
  }

  function reset() {
    state.items = [];
    state.usage = {};
    state.steps = 0;
    state.calls = 0;
    state.cost = 0;
    state.charge = 0;
    state.outcome = null;
    state.endedAt = null;
    blocks = new Map();
    calls = new Map();
    steps = new Map();
    attempts = [];
  }

  return { state, apply, reset };
}
