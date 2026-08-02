const NAMED_ENTITIES = {
  '&nbsp;': ' ',
  '&amp;': '&',
  '&lt;': '<',
  '&gt;': '>',
  '&quot;': '"',
  '&#39;': "'",
  '&apos;': "'",
  '&rsquo;': "'",
  '&lsquo;': "'",
  '&ldquo;': '"',
  '&rdquo;': '"',
  '&hellip;': '...',
  '&mdash;': '—',
  '&ndash;': '–',
  '&bull;': '•',
  '&middot;': '·',
  '&copy;': '©',
  '&reg;': '®',
  '&trade;': '™',
};

export function cleanDescription(text) {
  if (!text) return '';

  const decoded = text
    .replace(/&#x([0-9a-f]+);/gi, (_, hex) => {
      const cp = parseInt(hex, 16);
      return Number.isFinite(cp) && cp > 0 ? String.fromCodePoint(cp) : '';
    })
    .replace(/&#(\d+);/g, (_, dec) => {
      const cp = parseInt(dec, 10);
      return Number.isFinite(cp) && cp > 0 ? String.fromCodePoint(cp) : '';
    })
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(p|div|h[1-6]|li|ul|ol|tr|blockquote|section|article|header|footer)>/gi, '\n')
    .replace(/<li[^>]*>/gi, '\n• ')
    .replace(/<(p|div|h[1-6]|tr|section|article|header|footer)[^>]*>/gi, '\n')
    .replace(/<[^>]+>/g, '');

  return decoded
    .split(/\n/)
    .map((line) => {
      let cleaned = line;
      for (const [entity, value] of Object.entries(NAMED_ENTITIES)) {
        cleaned = cleaned.split(entity).join(value);
      }
      return cleaned.replace(/[ \t]+/g, ' ').trim();
    })
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/^•\s+$/gm, '')
    .replace(/^\s+$/gm, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}
