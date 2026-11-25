const textNode = value => ({ type: 'text', value });
const element = (tag, children = [], attributes = {}) => ({
  type: 'element',
  tag,
  children,
  attributes,
});

function safeHref(value) {
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
    return url.href;
  } catch {
    return null;
  }
}

function parseInline(source) {
  const nodes = [];
  const pattern = /(\x60[^\x60\n]+\x60|\*\*[^*\n]+\*\*|__[^_\n]+__|~~[^~\n]+~~|\*[^*\n]+\*|_[^_\n]+_|\[[^\]\n]+\]\(https?:\/\/[^)\s]+\))/g;
  let cursor = 0;

  for (const match of source.matchAll(pattern)) {
    const token = match[0];
    const index = match.index ?? 0;
    if (index > cursor) nodes.push(textNode(source.slice(cursor, index)));

    if (token.startsWith('\x60')) {
      nodes.push(element('code', [textNode(token.slice(1, -1))]));
    } else if (token.startsWith('**') || token.startsWith('__')) {
      nodes.push(element('strong', [textNode(token.slice(2, -2))]));
    } else if (token.startsWith('~~')) {
      nodes.push(element('s', [textNode(token.slice(2, -2))]));
    } else if (token.startsWith('*') || token.startsWith('_')) {
      nodes.push(element('em', [textNode(token.slice(1, -1))]));
    } else {
      const separator = token.indexOf('](');
      const label = token.slice(1, separator);
      const href = safeHref(token.slice(separator + 2, -1));
      if (href) nodes.push(element('a', [textNode(label)], { href }));
      else nodes.push(textNode(token));
    }
    cursor = index + token.length;
  }

  if (cursor < source.length) nodes.push(textNode(source.slice(cursor)));
  return nodes;
}

function splitTableRow(line) {
  const placeholder = '\u0000';
  return line.trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .replace(/\\\|/g, placeholder)
    .split('|')
    .map(cell => cell.replaceAll(placeholder, '|').trim());
}

function tableAlignment(separator) {
  const value = separator.trim();
  const left = value.startsWith(':');
  const right = value.endsWith(':');
  if (left && right) return 'center';
  if (right) return 'right';
  return 'left';
}

function isTableAt(lines, index) {
  if (index + 1 >= lines.length || !lines[index].includes('|')) return false;
  const cells = splitTableRow(lines[index + 1]);
  return cells.length > 0 && cells.every(cell => /^:?-{3,}:?$/.test(cell));
}

function isListLine(line) {
  return /^ {0,3}(?:[-*+]|\d+[.)])\s+/.test(line);
}

function isBlockStart(lines, index) {
  const line = lines[index] ?? '';
  return (
    /^ {0,3}\x60{3}/.test(line) ||
    /^ {0,3}#{1,6}\s+/.test(line) ||
    /^ {0,3}(?:-{3,}|_{3,}|\*{3,})\s*$/.test(line) ||
    /^ {0,3}>/.test(line) ||
    isListLine(line) ||
    isTableAt(lines, index)
  );
}

function parseBlocks(lines) {
  const nodes = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = line.match(/^ {0,3}\x60{3}([\w+-]*)\s*$/);
    if (fence) {
      const code = [];
      index += 1;
      while (index < lines.length && !/^ {0,3}\x60{3}\s*$/.test(lines[index])) {
        code.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      const attributes = fence[1] ? { className: 'language-' + fence[1] } : {};
      nodes.push(element('pre', [element('code', [textNode(code.join('\n'))], attributes)], { className: 'markdown-code' }));
      continue;
    }

    const heading = line.match(/^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) {
      nodes.push(element('h' + heading[1].length, parseInline(heading[2])));
      index += 1;
      continue;
    }

    if (/^ {0,3}(?:-{3,}|_{3,}|\*{3,})\s*$/.test(line)) {
      nodes.push(element('hr'));
      index += 1;
      continue;
    }

    if (/^ {0,3}>/.test(line)) {
      const quote = [];
      while (index < lines.length && /^ {0,3}>/.test(lines[index])) {
        quote.push(lines[index].replace(/^ {0,3}> ?/, ''));
        index += 1;
      }
      nodes.push(element('blockquote', parseBlocks(quote)));
      continue;
    }

    if (isTableAt(lines, index)) {
      const headings = splitTableRow(lines[index]);
      const separators = splitTableRow(lines[index + 1]).map(tableAlignment);
      const width = headings.length;
      const headerCells = headings.map((cell, column) =>
        element('th', parseInline(cell), { 'data-align': separators[column] ?? 'left' }),
      );
      const bodyRows = [];
      index += 2;

      while (index < lines.length && lines[index].trim() && lines[index].includes('|')) {
        const cells = splitTableRow(lines[index]);
        bodyRows.push(element('tr', Array.from({ length: width }, (_, column) =>
          element('td', parseInline(cells[column] ?? ''), { 'data-align': separators[column] ?? 'left' }),
        )));
        index += 1;
      }

      nodes.push(element('div', [
        element('table', [
          element('thead', [element('tr', headerCells)]),
          element('tbody', bodyRows),
        ]),
      ], { className: 'markdown-table-wrap' }));
      continue;
    }

    if (isListLine(line)) {
      const ordered = /^ {0,3}\d+[.)]\s+/.test(line);
      const items = [];
      const marker = ordered ? /^ {0,3}\d+[.)]\s+/ : /^ {0,3}[-*+]\s+/;
      while (index < lines.length && marker.test(lines[index])) {
        items.push(element('li', parseInline(lines[index].replace(marker, ''))));
        index += 1;
      }
      nodes.push(element(ordered ? 'ol' : 'ul', items));
      continue;
    }

    const paragraph = [];
    while (index < lines.length && lines[index].trim() && !isBlockStart(lines, index)) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    if (paragraph.length) {
      nodes.push(element('p', parseInline(paragraph.join(' '))));
    } else {
      // Preserve unsupported Markdown syntax as literal text instead of dropping it.
      nodes.push(element('p', [textNode(line)]));
      index += 1;
    }
  }

  return nodes;
}

/**
 * Parse the safe Markdown subset used by AI answers into a DOM-independent tree.
 * The caller must create DOM nodes and insert text using textContent/createTextNode;
 * never pass model output to innerHTML.
 */
export function parseMarkdown(markdown) {
  return parseBlocks(String(markdown ?? '').replace(/\r\n?/g, '\n').split('\n'));
}
