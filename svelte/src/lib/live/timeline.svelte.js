import { UNITS_PER_USD } from '../format.js';
import { contextLimit, contextOf, costOf } from './pricing.js';

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
  let codeBlocks = new Map();
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

  function push(item) {
    state.items.push(item);
    return state.items[state.items.length - 1];
  }

  function ensureBlock(step, type) {
    const k = `${step}:${type}`;
    let item = blocks.get(k);
    if (!item) {
      item = push({
        id: crypto.randomUUID(),
        at: new Date().toISOString(),
        step,
        type,
        text: '',
        signature: null,
        streaming: true
      });
      blocks.set(k, item);
    }
    return item;
  }

  function apply(frame) {
    const data = frame.data ?? {};
    const when = at(frame) ?? new Date().toISOString();

    switch (frame.kind) {
      case 'turn.start':
        state.turn = { id: data.turn_id, chat: data.chat_id, resumed: data.resumed ?? 0 };
        state.startedAt = when;
        push({ id: frame.id, at: when, type: 'prompt', text: data.prompt ?? '' });
        break;

      case 'attempt.start': {
        state.model = data.model ?? state.model;
        state.effort = data.effort ?? state.effort;
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
          budget: data.budget_usd
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
          messages: data.messages
        });
        steps.set(data.step, item);
        break;
      }

      case 'step.model': {
        const item = steps.get(data.step);
        if (item) item.model = data.model;
        state.model = data.model ?? state.model;
        state.contextLimit = contextLimit(state.model);
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

        const thinkItem = blocks.get(`${data.step}:think`);
        if (thinkItem) thinkItem.streaming = false;
        const textItem = blocks.get(`${data.step}:text`);
        if (textItem) textItem.streaming = false;
        break;
      }

      case 'block.think': {
        const item = ensureBlock(data.step ?? state.steps, 'think');
        item.text += (data.text ?? '');
        break;
      }

      case 'block.signature': {
        const item = ensureBlock(data.step ?? state.steps, 'think');
        item.signature = data.signature;
        break;
      }

      case 'block.text': {
        const item = ensureBlock(data.step ?? state.steps, 'text');
        item.text += (data.text ?? '');
        break;
      }

      case 'code.start': {
        state.calls += 1;
        const item = push({
          id: frame.id,
          at: when,
          type: 'code',
          step: data.step ?? state.steps,
          index: data.index,
          code: data.code,
          machine: data.machine || 'sandbox',
          status: 'running',
          output: '',
          error: null,
          exit_code: null,
          seconds: null,
          images: []
        });
        codeBlocks.set(data.index, item);
        break;
      }

      case 'code.end': {
        const item = codeBlocks.get(data.index);
        if (item) {
          item.status = (data.exit_code === 0 && !data.error) ? 'ok' : 'failed';
          item.machine = data.machine || item.machine;
          item.exit_code = data.exit_code;
          item.output = data.output || '';
          item.error = data.error;
          item.seconds = data.seconds;
          item.images = data.images ?? [];
        }
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
    blocks.clear();
    codeBlocks.clear();
    steps.clear();
    attempts = [];
  }

  return { state, apply, reset };
}
