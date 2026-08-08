import { Search, Send } from 'lucide-react';
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
  InputGroupText,
  InputGroupTextarea,
} from '../../components/ui/input-group';
import { Kbd } from '../../components/ui/kbd';
import { Stack } from '../parts';

export function InputGroupDemo() {
  return (
    <div className="max-w-lg space-y-6 rounded-xl border bg-card p-6">
      <Stack label="Inline addons">
        <InputGroup>
          <InputGroupAddon>
            <Search />
          </InputGroupAddon>
          <InputGroupInput placeholder="Search projects" />
          <InputGroupAddon align="inline-end">
            <Kbd>/</Kbd>
          </InputGroupAddon>
        </InputGroup>
      </Stack>
      <Stack label="Multiline action">
        <InputGroup>
          <InputGroupTextarea placeholder="Write a message" />
          <InputGroupAddon align="block-end" className="justify-between">
            <InputGroupText>Markdown supported</InputGroupText>
            <InputGroupButton size="icon-xs" aria-label="Send message">
              <Send />
            </InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
      </Stack>
    </div>
  );
}
