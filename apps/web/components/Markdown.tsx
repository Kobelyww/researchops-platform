"use client";

import ReactMarkdown from "react-markdown";

export function Markdown({ content }: { content: string }) {
  return (
    <div className="md">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  );
}
