import { Button } from '../../components/ui/button';
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '../../components/ui/sheet';

export function SheetDemo() {
  return (
    <div className="rounded-xl border bg-card p-6">
      <Sheet>
        <SheetTrigger asChild>
          <Button variant="outline">Open settings</Button>
        </SheetTrigger>
        <SheetContent side="right">
          <SheetHeader>
            <SheetTitle>Workspace settings</SheetTitle>
            <SheetDescription>
              Configure members, access, and notifications.
            </SheetDescription>
          </SheetHeader>
          <div className="my-6 rounded-md border p-4 text-sm text-muted-foreground">
            Settings content
          </div>
          <SheetFooter>
            <SheetClose asChild>
              <Button>Save</Button>
            </SheetClose>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </div>
  );
}
