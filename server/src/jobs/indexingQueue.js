// Target design: in-memory FIFO queue today, swappable for BullMQ/Redis
// later without changing callers. Lets /api/upload return immediately while
// chunking+embedding happens in the background; chat polls indexing_jobs
// (see migrations/002_knowledge_metadata.sql) for status.
const queue = [];
let processing = false;

export function enqueueIndexingJob(job) {
  queue.push(job);
  processQueue();
}

async function processQueue() {
  if (processing) return;
  processing = true;
  while (queue.length > 0) {
    const job = queue.shift();
    try {
      await job.run();
    } catch (err) {
      // TODO: persist failure to indexing_jobs.status = 'failed' once that
      // table is migrated in; for now just don't crash the queue.
      console.error('indexingQueue job failed:', err);
    }
  }
  processing = false;
}
