// Minimal structured logger. Swap for pino/winston later without touching call sites.
function timestamp() {
  return new Date().toISOString();
}

function format(level, message, meta) {
  const metaStr = meta && Object.keys(meta).length ? ` ${JSON.stringify(meta)}` : '';
  return `[${timestamp()}] ${level} ${message}${metaStr}`;
}

export default {
  info(message, meta = {}) {
    console.log(format('INFO', message, meta));
  },
  warn(message, meta = {}) {
    console.warn(format('WARN', message, meta));
  },
  error(message, meta = {}) {
    console.error(format('ERROR', message, meta));
  }
};
