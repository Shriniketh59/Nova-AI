// Builds the strict context-grounded prompt used by the RAG pipeline.
// Kept separate from the general-assistant prompt (rag_api/main.py) which
// is allowed to fall back to web knowledge — this one must not.
export function buildRagPrompt(context, question) {
  return `You are Nova AI.
Answer ONLY using the provided context.
If the answer is not present in the context, clearly state that the information was not found in the uploaded documents.

Context:
${context}

Question:
${question}`;
}
