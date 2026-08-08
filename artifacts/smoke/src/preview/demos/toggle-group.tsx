import { AlignCenter, AlignLeft, AlignRight } from 'lucide-react';
import {
  ToggleGroup,
  ToggleGroupItem,
} from '../../components/ui/toggle-group';
import { Stack } from '../parts';

export function ToggleGroupDemo() {
  return (
    <div className="max-w-sm space-y-6 rounded-xl border bg-card p-6">
      <Stack label="Single selection">
        <ToggleGroup type="single" defaultValue="left" variant="outline">
          <ToggleGroupItem value="left" aria-label="Align left">
            <AlignLeft />
          </ToggleGroupItem>
          <ToggleGroupItem value="center" aria-label="Align center">
            <AlignCenter />
          </ToggleGroupItem>
          <ToggleGroupItem value="right" aria-label="Align right">
            <AlignRight />
          </ToggleGroupItem>
        </ToggleGroup>
      </Stack>
      <Stack label="Multiple selection">
        <ToggleGroup type="multiple" size="sm" defaultValue={['bold']}>
          <ToggleGroupItem value="bold">Bold</ToggleGroupItem>
          <ToggleGroupItem value="italic">Italic</ToggleGroupItem>
        </ToggleGroup>
      </Stack>
    </div>
  );
}
