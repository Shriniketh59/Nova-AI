// Heuristic structural analysis — not a real static analyzer, just enough
// signal to sanity-check the model's own stated Big-O against what the code
// actually does, instead of trusting an LLM's complexity claim blindly.
// "Do not guess" in the spec means catch obvious mismatches (model writes a
// double-nested loop and calls it O(n)), not produce a provably correct
// derivation — that needs real AST analysis per language, out of scope here.
const LOOP_KEYWORDS = /\b(for|while)\b/g;
const RECURSION_HINT = /\bdef\s+(\w+)\s*\(|\b(\w+)\s*\([^)]*\)\s*\{/g;
const SORT_CALLS = /\.sort\(|Arrays\.sort|Collections\.sort|sorted\(/;

function maxLoopNestingDepth(code) {
  // Brace-depth tracking for C-family languages; indentation tracking for
  // Python. Approximate on purpose — this only needs to distinguish
  // "no loop" vs "single loop" vs "nested loop", not exact depth.
  const lines = code.split('\n');
  let depth = 0;
  let maxDepth = 0;
  const loopIndents = [];

  for (const line of lines) {
    const trimmed = line.trim();
    const indent = line.length - line.replace(/^\s*/, '').length;

    while (loopIndents.length > 0 && indent <= loopIndents[loopIndents.length - 1]) {
      loopIndents.pop();
    }
    if (/^(for|while)\b/.test(trimmed)) {
      loopIndents.push(indent);
      depth = loopIndents.length;
      maxDepth = Math.max(maxDepth, depth);
    }
  }
  return maxDepth;
}

function detectRecursion(code) {
  const defMatch = code.match(/\bdef\s+(\w+)\s*\(/) || code.match(/\b(?:public|private|protected|static|\s)*\w+\s+(\w+)\s*\([^)]*\)\s*\{/);
  if (!defMatch) return false;
  const fnName = defMatch[1];
  if (!fnName) return false;
  const calls = (code.match(new RegExp(`\\b${fnName}\\s*\\(`, 'g')) || []).length;
  return calls > 1; // defined once, called again inside its own body
}

export function analyzeStructure(code) {
  return {
    loopDepth: maxLoopNestingDepth(code),
    hasRecursion: detectRecursion(code),
    hasSort: SORT_CALLS.test(code)
  };
}

// Flags only blatant mismatches — a stated O(1)/O(log n) next to an actual
// nested loop, which is the failure mode that actually shows up (model
// copies a generic complexity line without checking its own code).
export function checkComplexityClaim(statedText, code) {
  const structure = analyzeStructure(code);
  const issues = [];
  const stated = statedText.toLowerCase();

  const claimsConstant = /\bo\(1\)/.test(stated);
  const claimsLog = /\bo\(log/.test(stated) && !/\bo\(n log/.test(stated);
  const claimsLinear = /\bo\(n\)\b/.test(stated) && !/\bo\(n[\s\S]{0,3}\^?2\)|\bo\(n²\)/.test(stated);

  if ((claimsConstant || claimsLog) && structure.loopDepth >= 1 && !structure.hasRecursion) {
    issues.push(`Stated complexity claims ${claimsConstant ? 'O(1)' : 'O(log n)'} but the code contains a loop — recheck the analysis.`);
  }
  if (claimsLinear && structure.loopDepth >= 2) {
    issues.push('Stated complexity claims O(n) but the code has nested loops (likely O(n^2) or worse) — recheck the analysis.');
  }

  return { pass: issues.length === 0, issues, structure };
}
