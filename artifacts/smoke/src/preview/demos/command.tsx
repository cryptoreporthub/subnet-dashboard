import { FileText, Settings, User } from 'lucide-react';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from '../../components/ui/command';

export function CommandDemo() {
  return (
    <div className="max-w-md overflow-hidden rounded-xl border bg-card shadow-sm">
      <Command>
        <CommandInput placeholder="Type a command" />
        <CommandList>
          <CommandEmpty>No results found.</CommandEmpty>
          <CommandGroup heading="Suggestions">
            <CommandItem>
              <FileText /> New document
              <CommandShortcut>Cmd N</CommandShortcut>
            </CommandItem>
            <CommandItem>
              <User /> View profile
            </CommandItem>
          </CommandGroup>
          <CommandSeparator />
          <CommandGroup heading="Settings">
            <CommandItem disabled>
              <Settings /> Team settings
            </CommandItem>
          </CommandGroup>
        </CommandList>
      </Command>
    </div>
  );
}
