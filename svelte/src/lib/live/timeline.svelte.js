import { contextLimit, contextOf } from './pricing.js';

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

  const at = (frame) => frame.at ?? null;

  function seeContext(usage, model) {
    const size = contextOf(usage);
    if (!size) return;
    state.context = size;
    state.contextPeak = Math.max(state.contextPeak, size);
    state.contextLimit = contextLimit(model ?? state.model);
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
        state.contextLimit = contextLimit(state.model);
        const item = push({
          id: frame.id,
          at: when,
          type: 'attempt',
          attempt: data.attempt,
          model: data.model,
          effort: data.effort
        });
        attempts.push(item);
        break;
      }

      case 'attempt.end': {
        const item = attempts[attempts.length - 1];
        if (item) {
          item.status = data.status;
          item.stop = data.stop_reason;
          item.error = data.error;
        }
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

      case 'step.end': {
        const item = steps.get(data.step);
        if (item) {
          item.model = data.model ?? item.model;
          item.stop = data.stop_reason;
          item.usage = data.usage ?? {};
          item.endedAt = when;
        }
        merge(state.usage, data.usage);
        seeContext(data.usage, data.model);

        const thinkItem = blocks.get(`${data.step}:think`);
        if (thinkItem) {
          thinkItem.streaming = false;
          if (!thinkItem.text.trim()) {
            const idx = state.items.indexOf(thinkItem);
            if (idx >= 0) state.items.splice(idx, 1);
            blocks.delete(`${data.step}:think`);
          }
        }
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
        const item = blocks.get(`${data.step ?? state.steps}:think`);
        if (item) item.signature = data.signature;
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
        push({
          id: frame.id,
          at: when,
          type: 'end',
          status: data.status,
          steps: data.steps,
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
