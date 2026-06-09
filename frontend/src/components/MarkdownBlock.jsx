import { memo, useMemo } from 'react';

const BLOCK_START = /^(#{1,4})\s+|^>\s?|^([-*+])\s+|^\d+[.)]\s+|^```|^\|.+\|\s*$/;

export const MarkdownBlock = memo(function MarkdownBlock({ content = '' }) {
  const blocks = useMemo(() => parseBlocks(content), [content]);
  return (
    <div className="markdown-block">
      {blocks.map((block, index) => renderBlock(block, index))}
    </div>
  );
});

function parseBlocks(content) {
  const lines = String(content || '').replace(/\r\n/g, '\n').split('\n');
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = line.match(/^```([\w-]*)\s*$/);
    if (fence) {
      const language = fence[1] || '';
      const code = [];
      index += 1;
      while (index < lines.length && !/^```\s*$/.test(lines[index])) {
        code.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      if (isMarkdownLanguage(language)) {
        blocks.push({ type: 'fragment', blocks: parseBlocks(code.join('\n')) });
      } else {
        blocks.push({ type: 'code', language, value: code.join('\n') });
      }
      continue;
    }

    if (isTableStart(lines, index)) {
      const tableLines = [lines[index], lines[index + 1]];
      index += 2;
      while (index < lines.length && /^\|.+\|\s*$/.test(lines[index])) {
        tableLines.push(lines[index]);
        index += 1;
      }
      blocks.push(parseTable(tableLines));
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, value: heading[2] });
      index += 1;
      continue;
    }

    if (/^>\s?/.test(line)) {
      const quote = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) {
        quote.push(lines[index].replace(/^>\s?/, ''));
        index += 1;
      }
      blocks.push({ type: 'quote', value: quote.join('\n') });
      continue;
    }

    if (/^[-*+]\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^[-*+]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^[-*+]\s+/, ''));
        index += 1;
      }
      blocks.push({ type: 'list', ordered: false, items });
      continue;
    }

    if (/^\d+[.)]\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^\d+[.)]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\d+[.)]\s+/, ''));
        index += 1;
      }
      blocks.push({ type: 'list', ordered: true, items });
      continue;
    }

    const paragraph = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !BLOCK_START.test(lines[index])) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ type: 'paragraph', value: paragraph.join('\n') });
  }

  return blocks.length ? blocks : [{ type: 'paragraph', value: '' }];
}

function renderBlock(block, key) {
  if (block.type === 'fragment') {
    return <div className="markdown-fragment" key={key}>{block.blocks.map((child, index) => renderBlock(child, `${key}-${index}`))}</div>;
  }
  if (block.type === 'heading') {
    const Tag = `h${Math.min(block.level, 5)}`;
    return <Tag key={key}>{renderInline(block.value, key)}</Tag>;
  }
  if (block.type === 'code') {
    return (
      <pre key={key}>
        <code>{block.value}</code>
      </pre>
    );
  }
  if (block.type === 'quote') {
    return <blockquote key={key}>{renderInline(block.value, key)}</blockquote>;
  }
  if (block.type === 'list') {
    const Tag = block.ordered ? 'ol' : 'ul';
    return (
      <Tag key={key}>
        {block.items.map((item, itemIndex) => <li key={itemIndex}>{renderInline(item, `${key}-${itemIndex}`)}</li>)}
      </Tag>
    );
  }
  if (block.type === 'table') {
    return (
      <div className="markdown-table-wrap" key={key}>
        <table>
          <thead>
            <tr>
              {block.headers.map((header, index) => <th key={index}>{renderInline(header, `${key}-h-${index}`)}</th>)}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {block.headers.map((_, cellIndex) => (
                  <td key={cellIndex}>{renderInline(row[cellIndex] || '', `${key}-${rowIndex}-${cellIndex}`)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return <p key={key}>{renderInline(block.value, key)}</p>;
}

function isMarkdownLanguage(language) {
  return ['markdown', 'md', 'mdown', 'mkd'].includes(String(language || '').toLowerCase());
}

function isTableStart(lines, index) {
  return (
    /^\|.+\|\s*$/.test(lines[index] || '')
    && /^\|\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|\s*$/.test(lines[index + 1] || '')
  );
}

function parseTable(lines) {
  const [headerLine, , ...rowLines] = lines;
  return {
    type: 'table',
    headers: splitTableRow(headerLine),
    rows: rowLines.map(splitTableRow),
  };
}

function splitTableRow(line) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

function renderInline(value, keyPrefix) {
  const nodes = [];
  let rest = value || '';
  let tokenIndex = 0;

  while (rest) {
    const matches = [
      findMatch(rest, /`([^`]+)`/, 'code'),
      findMatch(rest, /\[([^\]]+)\]\((https?:\/\/[^\s)]+|mailto:[^)]+)\)/, 'link'),
      findMatch(rest, /\*\*([^*]+)\*\*/, 'strong'),
      findMatch(rest, /\*([^*]+)\*/, 'em'),
    ].filter(Boolean).sort((left, right) => left.index - right.index);

    const match = matches[0];
    if (!match) {
      pushText(nodes, rest, `${keyPrefix}-t-${tokenIndex++}`);
      break;
    }

    if (match.index > 0) {
      pushText(nodes, rest.slice(0, match.index), `${keyPrefix}-t-${tokenIndex++}`);
    }

    if (match.type === 'code') {
      nodes.push(<code key={`${keyPrefix}-c-${tokenIndex++}`}>{match.match[1]}</code>);
    } else if (match.type === 'link') {
      nodes.push(
        <a key={`${keyPrefix}-a-${tokenIndex++}`} href={match.match[2]} target="_blank" rel="noreferrer">
          {match.match[1]}
        </a>,
      );
    } else if (match.type === 'strong') {
      nodes.push(<strong key={`${keyPrefix}-s-${tokenIndex++}`}>{renderInline(match.match[1], `${keyPrefix}-s-${tokenIndex}`)}</strong>);
    } else if (match.type === 'em') {
      nodes.push(<em key={`${keyPrefix}-e-${tokenIndex++}`}>{renderInline(match.match[1], `${keyPrefix}-e-${tokenIndex}`)}</em>);
    }

    rest = rest.slice(match.index + match.match[0].length);
  }

  return nodes;
}

function findMatch(value, regex, type) {
  const match = regex.exec(value);
  return match ? { type, match, index: match.index } : null;
}

function pushText(nodes, text, keyPrefix) {
  text.split('\n').forEach((part, index, parts) => {
    if (part) nodes.push(part);
    if (index < parts.length - 1) nodes.push(<br key={`${keyPrefix}-br-${index}`} />);
  });
}
