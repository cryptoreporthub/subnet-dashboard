import { Command } from 'lucide-react';
import { Kbd, KbdGroup } from '../../components/ui/kbd';
import { Row } from '../parts';

export function KbdDemo() {
  return (
    <div className="rounded-xl border bg-card p-6">
      <Row label="Keyboard shortcuts">
        <Kbd>Esc</Kbd>
        <KbdGroup>
          <Kbd>
            <Command />
          </Kbd>
          <span>+</span>
          <Kbd>K</Kbd>
        </KbdGroup>
        <KbdGroup>
          <Kbd>Ctrl</Kbd>
          <span>+</span>
          <Kbd>Enter</Kbd>
        </KbdGroup>
      </Row>
    </div>
  );
}
