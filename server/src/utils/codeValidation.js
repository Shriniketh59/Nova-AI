import { checkComplexityClaim } from './complexityAnalyzer.js';

// "Quick Review Mode" — cheap static checks instead of a second LLM critique
// call. Catches the failure modes that actually show up in generated code
// (unclosed fence, unbalanced braces, an import obviously missing for a
// function it uses) without the latency of a full reasoning pass.
const BRACE_PAIRS = [['{', '}'], ['(', ')'], ['[', ']']];

const IMPORT_HINTS = [
  { lang: 'python', uses: /\bnp\./, importRe: /^\s*import\s+numpy/m, missing: 'numpy' },
  { lang: 'python', uses: /\bpd\./, importRe: /^\s*import\s+pandas/m, missing: 'pandas' },
  { lang: 'javascript', uses: /\baxios\./, importRe: /require\(['"]axios['"]\)|from ['"]axios['"]/, missing: 'axios' },
  { lang: 'java', uses: /\bList</, importRe: /import\s+java\.util\.(List|\*)/, missing: 'java.util.List' },
  { lang: 'java', uses: /\bArrayList</, importRe: /import\s+java\.util\.(ArrayList|\*)/, missing: 'java.util.ArrayList' },
  { lang: 'java', uses: /\bHashMap</, importRe: /import\s+java\.util\.(HashMap|\*)/, missing: 'java.util.HashMap' },
  { lang: 'java', uses: /\bScanner\(/, importRe: /import\s+java\.util\.(Scanner|\*)/, missing: 'java.util.Scanner' },
];

function extractCodeBlocks(text) {
  const blocks = [];
  const re = /```(\w+)?\n([\s\S]*?)```/g;
  let m;
  while ((m = re.exec(text))) {
    blocks.push({ lang: (m[1] || '').toLowerCase(), code: m[2] });
  }
  return blocks;
}

function checkBraceBalance(code) {
  const issues = [];
  for (const [open, close] of BRACE_PAIRS) {
    const opens = (code.match(new RegExp(`\\${open}`, 'g')) || []).length;
    const closes = (code.match(new RegExp(`\\${close}`, 'g')) || []).length;
    if (opens !== closes) {
      issues.push(`Unbalanced ${open}${close}: ${opens} open vs ${closes} close`);
    }
  }
  return issues;
}

function checkMissingImports(lang, code) {
  return IMPORT_HINTS
    .filter(h => (h.lang === lang) && h.uses.test(code) && !h.importRe.test(code))
    .map(h => `Uses ${h.missing} without importing it`);
}

// A function with a non-void/non-None-implied signature that never hits a
// return is the single most common "looks right, doesn't work" defect in
// generated code — model writes the logic, forgets to return the result.
function checkMissingReturn(lang, code) {
  const issues = [];
  if (lang === 'python') {
    const defs = code.match(/def\s+\w+\([^)]*\)\s*:/g) || [];
    for (const def of defs) {
      const name = def.match(/def\s+(\w+)/)[1];
      if (name === '__init__') continue; // constructors legitimately return nothing
      const bodyMatch = code.slice(code.indexOf(def)).match(/:\n([\s\S]*?)(?=\ndef\s|\nclass\s|$)/);
      const body = bodyMatch ? bodyMatch[1] : '';
      if (body.trim() && !/\breturn\b/.test(body) && !/\byield\b/.test(body) && !/\bprint\(/.test(body)) {
        issues.push(`Function "${name}" has no return statement — likely meant to return a value`);
      }
    }
  }
  if (lang === 'java') {
    // Methods declared with a non-void return type but whose body has no
    // "return" anywhere are almost always a forgotten result.
    const methodRe = /\b(?!void\b)(?:public|private|protected|static|\s)*[\w<>[\],\s]+\s+(\w+)\s*\([^)]*\)\s*\{/g;
    let m;
    while ((m = methodRe.exec(code))) {
      const start = m.index + m[0].length;
      let depth = 1;
      let i = start;
      while (i < code.length && depth > 0) {
        if (code[i] === '{') depth++;
        if (code[i] === '}') depth--;
        i++;
      }
      const body = code.slice(start, i - 1);
      if (body.trim() && !/\breturn\b/.test(body) && !/\bvoid\b/.test(m[0]) && !/^(class|interface)\b/.test(m[1])) {
        issues.push(`Method "${m[1]}" has a non-void signature but no return statement`);
      }
    }
  }
  return issues;
}

// Loops with no apparent way to terminate — "while True"/"while(true)" with
// no break anywhere in the loop body is the classic infinite-loop bug.
function checkInfiniteLoopRisk(code) {
  const issues = [];
  const re = /\bwhile\s*\(?\s*(true|True|1)\s*\)?\s*[:{]/g;
  let m;
  while ((m = re.exec(code))) {
    const after = code.slice(m.index, m.index + 500);
    if (!/\bbreak\b/.test(after) && !/\breturn\b/.test(after)) {
      issues.push('while(true)/while True loop with no break or return found in scanned range — possible infinite loop');
    }
  }
  return issues;
}

// Java specifically: a `public class Foo` must live in a file/code block
// that is otherwise self-contained — flag an unterminated class body
// (brace check already catches this generally, but name it specifically
// for Java since "missing class" is its own spec requirement).
function checkJavaStructure(code) {
  const issues = [];
  if (/\bpublic\s+class\s+(\w+)/.test(code) && !/\}\s*$/.test(code.trim())) {
    issues.push('Java class does not appear to close with a final closing brace');
  }
  return issues;
}

// Returns { pass, issues } — issues are strings naming the specific defect,
// not a regenerate-from-scratch verdict. Caller decides what to do with them.
export function quickValidateCode(answerText) {
  const issues = [];

  if ((answerText.match(/```/g) || []).length % 2 !== 0) {
    issues.push('Unclosed code fence');
  }

  const blocks = extractCodeBlocks(answerText);
  if (blocks.length === 0) {
    issues.push('No code block found in response');
  }

  for (const block of blocks) {
    issues.push(...checkBraceBalance(block.code));
    issues.push(...checkMissingImports(block.lang, block.code));
    issues.push(...checkMissingReturn(block.lang, block.code));
    issues.push(...checkInfiniteLoopRisk(block.code));
    if (block.lang === 'java') issues.push(...checkJavaStructure(block.code));
  }

  // Cross-check the model's own stated Big-O against the code's loop/
  // recursion structure — only flag blatant mismatches (see complexityAnalyzer).
  if (blocks.length > 0) {
    const complexityCheck = checkComplexityClaim(answerText, blocks[0].code);
    issues.push(...complexityCheck.issues);
  }

  return { pass: issues.length === 0, issues };
}
