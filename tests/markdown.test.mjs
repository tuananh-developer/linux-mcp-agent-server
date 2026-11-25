import test from 'node:test';
import assert from 'node:assert/strict';
import { parseMarkdown } from '../src/linux_mcp_agent/web/markdown.mjs';

function findNodes(nodes, tag) {
  return nodes.flatMap(node => {
    if (node.type !== 'element') return [];
    return [
      ...(node.tag === tag ? [node] : []),
      ...findNodes(node.children ?? [], tag),
    ];
  });
}

function textContent(nodes) {
  return nodes.map(node => node.type === 'text'
    ? node.value
    : textContent(node.children ?? [])).join('');
}

test('parses assistant headings, emphasis, inline code, lists and tables', () => {
  const nodes = parseMarkdown([
    '## Memory usage',
    '',
    '**firefox** uses \x60497 MB\x60.',
    '',
    '| PID | Process | RAM |',
    '| --- | :---: | ---: |',
    '| 12 | java | 466 MB |',
    '| 13 | shell | 427 MB |',
    '',
    '- First',
    '- Second',
  ].join('\n'));

  assert.equal(findNodes(nodes, 'h2').length, 1);
  assert.equal(findNodes(nodes, 'strong').length, 1);
  assert.equal(findNodes(nodes, 'code').length, 1);
  assert.equal(findNodes(nodes, 'table').length, 1);
  assert.equal(findNodes(nodes, 'th').length, 3);
  assert.equal(findNodes(nodes, 'tr').length, 3);
  assert.equal(findNodes(nodes, 'ul').length, 1);
  assert.equal(findNodes(nodes, 'li').length, 2);
  assert.match(textContent(nodes), /firefox uses 497 MB/);
});

test('keeps raw HTML as text and only creates safe HTTP(S) links', () => {
  const rawHtml = '<img src=x onerror="alert(1)">';
  const nodes = parseMarkdown([
    rawHtml,
    '',
    '[unsafe](javascript:alert(1))',
    '',
    '[safe](https://example.com/path)',
  ].join('\n'));

  const links = findNodes(nodes, 'a');
  assert.equal(findNodes(nodes, 'img').length, 0);
  assert.equal(links.length, 1);
  assert.equal(links[0].attributes.href, 'https://example.com/path');
  assert.ok(textContent(nodes).includes(rawHtml));
  assert.ok(textContent(nodes).includes('[unsafe](javascript:alert(1))'));
});

test('parses fenced code blocks without interpreting their contents as markup', () => {
  const fence = '\x60\x60\x60';
  const nodes = parseMarkdown([
    fence + 'bash',
    'echo "<script>alert(1)</script>"',
    fence,
  ].join('\n'));

  const pre = findNodes(nodes, 'pre');
  assert.equal(pre.length, 1);
  assert.equal(findNodes(pre, 'code').length, 1);
  assert.equal(textContent(pre), 'echo "<script>alert(1)</script>"');
  assert.equal(findNodes(pre, 'script').length, 0);
});
