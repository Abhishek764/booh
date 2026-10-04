import type { ReactNode } from "react";

type EmptyStateProps = {
  headingId: string;
  title: string;
  description: string;
  action?: ReactNode;
};

/** Plain text is escaped by React. Optional actions stay explicit at the caller. */
export function EmptyState({ headingId, title, description, action }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <h2 id={headingId}>{title}</h2>
      <p>{description}</p>
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  );
}
