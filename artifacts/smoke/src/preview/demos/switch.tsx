import { Label } from '../../components/ui/label';
import { Switch } from '../../components/ui/switch';
import { Stack } from '../parts';

export function SwitchDemo() {
  return (
    <div className="max-w-sm rounded-xl border bg-card p-6">
      <Stack label="Preferences">
        <div className="flex items-center justify-between gap-6">
          <Label htmlFor="switch-notifications">Notifications</Label>
          <Switch id="switch-notifications" defaultChecked />
        </div>
        <div className="flex items-center justify-between gap-6">
          <Label htmlFor="switch-sync">Background sync</Label>
          <Switch id="switch-sync" />
        </div>
        <div className="flex items-center justify-between gap-6">
          <Label htmlFor="switch-disabled">Unavailable</Label>
          <Switch id="switch-disabled" disabled />
        </div>
      </Stack>
    </div>
  );
}
