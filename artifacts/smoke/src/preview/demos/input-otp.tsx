import {
  InputOTP,
  InputOTPGroup,
  InputOTPSeparator,
  InputOTPSlot,
} from '../../components/ui/input-otp';
import { Stack } from '../parts';

export function InputOtpDemo() {
  return (
    <div className="max-w-sm rounded-xl border bg-card p-6">
      <Stack label="Six digit code">
        <InputOTP maxLength={6} defaultValue="123">
          <InputOTPGroup>
            <InputOTPSlot index={0} />
            <InputOTPSlot index={1} />
            <InputOTPSlot index={2} />
          </InputOTPGroup>
          <InputOTPSeparator />
          <InputOTPGroup>
            <InputOTPSlot index={3} />
            <InputOTPSlot index={4} />
            <InputOTPSlot index={5} />
          </InputOTPGroup>
        </InputOTP>
      </Stack>
    </div>
  );
}
