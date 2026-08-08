import { Slider } from '../../components/ui/slider';
import { Stack } from '../parts';

export function SliderDemo() {
  return (
    <div className="max-w-md space-y-6 rounded-xl border bg-card p-6">
      <Stack label="Value">
        <Slider defaultValue={[40]} max={100} step={1} />
      </Stack>
      <Stack label="Range">
        <Slider defaultValue={[25, 75]} max={100} step={5} />
      </Stack>
      <Stack label="Disabled">
        <Slider defaultValue={[60]} disabled />
      </Stack>
    </div>
  );
}
