import { Bold, Italic, Underline } from 'lucide-react';
import { Toggle } from '../../components/ui/toggle';
import { Row } from '../parts';

export function ToggleDemo() {
  return (
    <div className="space-y-6 rounded-xl border bg-card p-6">
      <Row label="Variants">
        <Toggle aria-label="Toggle bold" defaultPressed>
          <Bold />
        </Toggle>
        <Toggle variant="outline" aria-label="Toggle italic">
          <Italic />
        </Toggle>
      </Row>
      <Row label="Sizes and states">
        <Toggle size="sm" aria-label="Small underline">
          <Underline />
        </Toggle>
        <Toggle size="lg" aria-label="Large underline">
          <Underline />
        </Toggle>
        <Toggle disabled aria-label="Disabled bold">
          <Bold />
        </Toggle>
      </Row>
    </div>
  );
}
