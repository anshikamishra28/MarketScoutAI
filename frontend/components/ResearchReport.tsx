import type { ReactNode } from "react";

interface ResearchReportProps { content: string }

function inline(text: string): ReactNode[] {
  const token = /(\[[^\]]+\]\(https?:\/\/[^\s)]+\)|\*\*[^*]+\*\*|`[^`]+`)/g;
  const output: ReactNode[] = [];
  let cursor = 0;
  for (const match of text.matchAll(token)) {
    const value = match[0];
    const index = match.index ?? 0;
    if (index > cursor) output.push(text.slice(cursor, index));
    if (value.startsWith("[")) {
      const parsed = value.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
      output.push(parsed ? <a key={`${index}-${value}`} href={parsed[2]} target="_blank" rel="noopener noreferrer">{parsed[1]}</a> : value);
    } else if (value.startsWith("**")) output.push(<strong key={`${index}-${value}`}>{value.slice(2, -2)}</strong>);
    else output.push(<code key={`${index}-${value}`}>{value.slice(1, -1)}</code>);
    cursor = index + value.length;
  }
  if (cursor < text.length) output.push(text.slice(cursor));
  return output;
}

export function ResearchReport({ content }: ResearchReportProps) {
  const lines = content.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) { index += 1; continue; }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      const text = inline(heading[2]);
      const key = `h-${index}`;
      blocks.push(level === 1 ? <h2 key={key}>{text}</h2> : level === 2 ? <h3 key={key}>{text}</h3> : <h4 key={key}>{text}</h4>);
      index += 1;
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      const items: ReactNode[] = [];
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(<li key={`ul-${index}`}>{inline(lines[index].trim().replace(/^[-*]\s+/, ""))}</li>);
        index += 1;
      }
      blocks.push(<ul key={`ul-block-${index}`}>{items}</ul>);
      continue;
    }
    if (/^\d+[.)]\s+/.test(line)) {
      const items: ReactNode[] = [];
      while (index < lines.length && /^\s*\d+[.)]\s+/.test(lines[index])) {
        items.push(<li key={`ol-${index}`}>{inline(lines[index].trim().replace(/^\d+[.)]\s+/, ""))}</li>);
        index += 1;
      }
      blocks.push(<ol key={`ol-block-${index}`}>{items}</ol>);
      continue;
    }
    const paragraph = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !/^(#{1,4}\s|[-*]\s+|\d+[.)]\s+)/.test(lines[index].trim())) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push(<p key={`p-${index}`}>{inline(paragraph.join(" "))}</p>);
  }
  return <article className="panel report">
    <div className="panel-title"><h3>Final market intelligence report</h3><span>Backend generated</span></div>
    <div className="markdown">{blocks.length ? blocks : <p>Report content is empty.</p>}</div>
  </article>;
}
