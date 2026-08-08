import { AlertCircle, CheckCircle2 } from 'lucide-react';
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from '../../components/ui/alert';
import { Stack } from '../parts';

export function AlertDemo() {
  return (
    <div className="max-w-xl rounded-xl border bg-card p-6">
      <Stack label="Variants">
        <Alert>
          <CheckCircle2 />
          <AlertTitle>Deployment complete</AlertTitle>
          <AlertDescription>Your latest changes are now live.</AlertDescription>
        </Alert>
        <Alert variant="destructive">
          <AlertCircle />
          <AlertTitle>Connection failed</AlertTitle>
          <AlertDescription>Check your credentials and try again.</AlertDescription>
        </Alert>
      </Stack>
    </div>
  );
}
