import { describe, it, expect } from 'vitest';
import { classifyDomain, rankSources, countTrustTiers } from '../src/retrieval/sourceTrust.js';

describe('sourceTrust', () => {
  it('classifies official, reference, community, and unknown domains', () => {
    expect(classifyDomain('https://www.cdc.gov/some-page')).toBe('official');
    expect(classifyDomain('https://mit.edu/about')).toBe('official');
    expect(classifyDomain('https://en.wikipedia.org/wiki/Foo')).toBe('reference');
    expect(classifyDomain('https://stackoverflow.com/questions/1')).toBe('community');
    expect(classifyDomain('https://random-seo-blog.xyz/article')).toBe('unknown');
    expect(classifyDomain('not a url')).toBe('unknown');
  });

  it('tags sources with trustTier without dropping any', () => {
    const sources = [
      { url: 'https://random-seo-blog.xyz/a' },
      { url: 'https://cdc.gov/b' },
      { url: 'https://stackoverflow.com/c' }
    ];
    const ranked = rankSources(sources);
    expect(ranked).toHaveLength(3);
    expect(ranked.find(s => s.url.includes('cdc')).trustTier).toBe('official');
  });

  it('counts sources per trust tier', () => {
    const sources = [{ trustTier: 'official' }, { trustTier: 'unknown' }, { trustTier: 'unknown' }];
    expect(countTrustTiers(sources)).toEqual({ official: 1, reference: 0, community: 0, unknown: 2 });
  });
});
