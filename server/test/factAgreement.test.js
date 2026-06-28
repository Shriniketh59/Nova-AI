import { describe, it, expect } from 'vitest';
import { detectFactDisagreements } from '../src/agents/researchAgent.js';

describe('fact agreement check', () => {
  it('flags a year disagreement between two sources about the same entity', () => {
    const evidence = [
      { title: 'Source A', snippet: 'Marcus Wilkins founded Initech in 1998.' },
      { title: 'Source B', snippet: 'Marcus Wilkins founded Initech in 2003.' }
    ];
    const disagreements = detectFactDisagreements(evidence);
    expect(disagreements).toHaveLength(1);
    expect(disagreements[0].factType).toBe('year');
    expect(disagreements[0].valueA).toBe('1998');
    expect(disagreements[0].valueB).toBe('2003');
  });

  it('does not flag sources about different entities even if years differ', () => {
    const evidence = [
      { title: 'Source A', snippet: 'Marcus Wilkins founded Initech in 1998.' },
      { title: 'Source B', snippet: 'Priya Chandran founded Globex in 2003.' }
    ];
    expect(detectFactDisagreements(evidence)).toHaveLength(0);
  });

  it('does not flag sources that agree on the year', () => {
    const evidence = [
      { title: 'Source A', snippet: 'Marcus Wilkins founded Initech in 1998.' },
      { title: 'Source B', snippet: 'Marcus Wilkins started Initech back in 1998.' }
    ];
    expect(detectFactDisagreements(evidence)).toHaveLength(0);
  });
});
