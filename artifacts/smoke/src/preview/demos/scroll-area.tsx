import { ScrollArea, ScrollBar } from '../../components/ui/scroll-area';

export function ScrollAreaDemo() {
  return (
    <div className="grid max-w-2xl gap-4 md:grid-cols-2">
      <ScrollArea className="h-48 rounded-xl border bg-card p-4">
        <div className="space-y-3 pr-4">
          {Array.from({ length: 12 }, (_, index) => (
            <div key={index} className="border-b pb-3 text-sm last:border-0">
              Activity item {index + 1}
            </div>
          ))}
        </div>
      </ScrollArea>
      <ScrollArea className="w-full rounded-xl border bg-card p-4">
        <div className="flex w-max gap-3 pb-3">
          {['Alpha', 'Beta', 'Gamma', 'Delta', 'Epsilon'].map((label) => (
            <div
              key={label}
              className="flex h-32 w-32 items-end rounded-lg bg-muted p-3 text-sm font-medium"
            >
              {label}
            </div>
          ))}
        </div>
        <ScrollBar orientation="horizontal" />
      </ScrollArea>
    </div>
  );
}
