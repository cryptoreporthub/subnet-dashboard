import { toast } from 'sonner';
import { Button } from '../../components/ui/button';
import { Toaster } from '../../components/ui/sonner';
import { Row } from '../parts';

export function SonnerDemo() {
  return (
    <div className="rounded-xl border bg-card p-6">
      <Row label="Notifications">
        <Button onClick={() => toast.success('Project published')}>Success</Button>
        <Button
          variant="outline"
          onClick={() =>
            toast('Invitation sent', {
              description: 'alex@example.com can now join the workspace.',
              action: { label: 'Undo', onClick: () => undefined },
            })
          }
        >
          With action
        </Button>
      </Row>
      <Toaster />
    </div>
  );
}
