import type { ReactNode } from 'react';

export function Row({
  label,
  children,
}: {
  label?: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-2">
      {label ? (
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">{children}</div>
    </div>
  );
}

export function Stack({
  label,
  children,
}: {
  label?: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-2">
      {label ? (
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
      ) : null}
      <div className="flex flex-col gap-3">{children}</div>
    </div>
  );
}

export function Guidelines({
  items,
}: {
  items: Array<{ kind: 'do' | 'dont'; text: string }>;
}) {
  return (
    <ul className="space-y-2 text-sm">
      {items.map((item) => (
        <li key={`${item.kind}-${item.text}`} className="flex gap-3">
          <span
            className={`shrink-0 font-medium ${
              item.kind === 'do' ? 'text-primary' : 'text-destructive'
            }`}
          >
            {item.kind === 'do' ? 'Do' : "Don't"}
          </span>
          <span className="text-muted-foreground">{item.text}</span>
        </li>
      ))}
    </ul>
  );
}
