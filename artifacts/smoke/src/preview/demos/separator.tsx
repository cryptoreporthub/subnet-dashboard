import { Separator } from '../../components/ui/separator';

export function SeparatorDemo() {
  return (
    <div className="max-w-md rounded-xl border bg-card p-6">
      <div>
        <p className="font-medium">Design system</p>
        <p className="text-sm text-muted-foreground">Reusable interface foundations.</p>
      </div>
      <Separator className="my-4" />
      <div className="flex h-5 items-center gap-4 text-sm">
        <span>Docs</span>
        <Separator orientation="vertical" />
        <span>Components</span>
        <Separator orientation="vertical" />
        <span>Patterns</span>
      </div>
    </div>
  );
}
