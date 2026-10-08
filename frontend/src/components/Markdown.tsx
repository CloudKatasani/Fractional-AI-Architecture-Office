import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Children, ReactNode, isValidElement, cloneElement } from "react";
import { TextWithChips } from "./Evidence";

function chipify(children: ReactNode): ReactNode {
  return Children.map(children, (c) => {
    if (typeof c === "string") return <TextWithChips text={c} />;
    if (isValidElement(c) && (c.props as any)?.children) {
      return cloneElement(c as any, {}, chipify((c.props as any).children));
    }
    return c;
  });
}

/** Markdown renderer where `[RECORD-ID]` tokens become evidence chips. */
export function Markdown({ text }: { text?: string | null }) {
  if (!text) return null;
  return (
    <div className="prose-sm-custom text-sm">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p>{chipify(children)}</p>,
          li: ({ children }) => <li>{chipify(children)}</li>,
          td: ({ children }) => <td>{chipify(children)}</td>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
