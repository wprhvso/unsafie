import { UNITS_PER_USD } from '../format.js';
import { contextLimit, contextOf, costOf } from './pricing.js';

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
    configured: null,
    thinking: null,
    steps: 0,
    calls: 0,
    cost: 0,
    settled: 0,
    pending: 0,
    charge: 0,
    spent: 0,
    ratio: null,
    budget: null,
    balance: null,
    usage: {},
    context: 0,
    contextPeak: 0,
    contextLimit: contextLimit(null),
    startedAt: null,
    endedAt: null,
    outcome: null
  });

  let blocks = new Map();
  let calls = new Map();
  let steps = new Map();
  let attempts = [];
  let balanceStart = null;

  const at = (frame) => frame.at ?? null;

  function seeContext(usage, model) {
    const size = contextOf(usage);
    if (!size) return;
    state.context = size;
    state.contextPeak = Math.max(state.contextPeak, size);
    state.contextLimit = contextLimit(model ?? state.model);
  }

  function total() {
    state.cost = state.settled + state.pending;
    state.spent = state.charge / UNITS_PER_USD + state.pending * (state.ratio ?? 1);
    if (balanceStart !== null) state.balance = Math.max(balanceStart - state.spent, 0);
  }
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
      item = {
        ...base,
        type: 'think',
        text: '',
        redacted: kind === 'redacted_thinking',
        display: state.display,
        configured: state.configured
      };
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

  function downgraded(dropped) {
    const fields = Array.isArray(dropped) ? dropped : [dropped];
    if (fields.includes('thinking')) state.thinking = 'off';
    if (fields.includes('thinking') || fields.includes('thinking.display')) state.display = 'off';
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
        state.configured = data.configured ?? state.configured;
        state.thinking = data.thinking ?? state.thinking;
        state.ratio = typeof data.ratio === 'number' ? data.ratio : state.ratio;
        if (typeof data.budget_units === 'number')
          state.budget = data.budget_units / UNITS_PER_USD + state.spent;
        if (typeof data.balance_units === 'number')
          balanceStart = data.balance_units / UNITS_PER_USD;
        state.contextLimit = contextLimit(state.model);
        total();
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
          display: data.display,
          configured: data.configured
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
        state.settled =
          typeof data.total_cost === 'number'
            ? data.total_cost
            : state.settled + (data.cost_usd ?? 0);
        state.charge =
          typeof data.total_charge === 'number'
            ? data.total_charge
            : state.charge + (data.charge ?? 0);
        state.pending = 0;
        total();
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
        state.model = data.model ?? state.model;
        state.contextLimit = contextLimit(state.model);
        seeContext(data.usage, data.model);
        break;
      }

      case 'charge': {
        if (typeof data.total === 'number') state.charge = data.total;
        if (typeof data.cost_usd === 'number') state.settled = data.cost_usd;
        state.pending = 0;
        if (typeof data.balance === 'number')
          balanceStart = (data.balance + state.charge) / UNITS_PER_USD;
        total();
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
        state.pending += costOf(data.usage, data.model ?? state.model);
        seeContext(data.usage, data.model);
        total();
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
        if (data.name === 'unsafie.downgraded') downgraded(data.attributes?.dropped);
        push({ id: frame.id, at: when, type: 'note', name: data.name, attributes: data.attributes });
        break;

      case 'error':
        push({ id: frame.id, at: when, type: 'error', message: data.message, errorType: data.type });
        break;

      case 'turn.end':
        state.endedAt = when;
        state.outcome = data.status;
        if (typeof data.charge === 'number') state.charge = data.charge;
        if (typeof data.cost_usd === 'number') state.settled = data.cost_usd;
        state.pending = 0;
        total();
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
    state.settled = 0;
    state.pending = 0;
    state.charge = 0;
    state.spent = 0;
    state.balance = null;
    balanceStart = null;
    state.context = 0;
    state.contextPeak = 0;
    state.outcome = null;
    state.endedAt = null;
    blocks = new Map();
    calls = new Map();
    steps = new Map();
    attempts = [];
  }

  return { state, apply, reset };
}
