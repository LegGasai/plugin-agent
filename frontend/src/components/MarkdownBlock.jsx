import { memo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const markdownComponents = {
  a({ node: _node, ...props }) {
    return <a {...props} target="_blank" rel="noreferrer" />;
  },
  img({ node: _node, className = '', alt = '', ...props }) {
    return <img {...props} className={['markdown-image', className].filter(Boolean).join(' ')} alt={alt} loading="lazy" />;
  },
  table({ node: _node, ...props }) {
    return (
      <div className="markdown-table-wrap">
        <table {...props} />
      </div>
    );
  },
};

export const MarkdownBlock = memo(function MarkdownBlock({ content = '' }) {
  return (
    <div className="markdown-block">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={markdownComponents}
      >
        {String(content || '')}
      </ReactMarkdown>
    </div>
  );
});
