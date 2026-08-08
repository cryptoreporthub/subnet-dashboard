import { Checkbox } from '../../components/ui/checkbox';
import { Label } from '../../components/ui/label';
import { Stack } from '../parts';

export function CheckboxDemo() {
  return (
    <div className="max-w-sm rounded-xl border bg-card p-6">
      <Stack label="States">
        <div className="flex items-center gap-2">
          <Checkbox id="checkbox-terms" defaultChecked />
          <Label htmlFor="checkbox-terms">Accept terms</Label>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox id="checkbox-updates" />
          <Label htmlFor="checkbox-updates">Product updates</Label>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox id="checkbox-disabled" disabled />
          <Label htmlFor="checkbox-disabled">Unavailable</Label>
        </div>
      </Stack>
    </div>
  );
}
