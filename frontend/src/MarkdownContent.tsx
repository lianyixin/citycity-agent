import { ReactNode } from 'react';

type MarkdownContentProps = {
  content: string;
  className?: string;
};

function parseInlineMarkdown(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const pattern = /\*\*([^*]+)\*\*|\*([^*]+)\*/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    if (match[1]) {
      parts.push(<strong key={key++}>{match[1]}</strong>);
    } else if (match[2]) {
      parts.push(<em key={key++}>{match[2]}</em>);
    }
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length > 0 ? parts : [text];
}

export default function MarkdownContent({ content, className = 'markdown-content' }: MarkdownContentProps) {
  const blocks = content.split(/\n{2,}/);

  return (
    <div className={className}>
      {blocks.map((block, index) => {
        const trimmed = block.trim();
        if (!trimmed) {
          return null;
        }
        return (
          <p key={index} className="xhs-paragraph">
            {parseInlineMarkdown(trimmed)}
          </p>
        );
      })}
    </div>
  );
}
