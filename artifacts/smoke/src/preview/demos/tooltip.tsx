import { Info } from 'lucide-react';
import { Button } from '../../components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '../../components/ui/tooltip';

export function TooltipDemo() {
  return (
    <div className="rounded-xl border bg-card p-6">
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="outline" size="icon" aria-label="More information">
              <Info />
            </Button>
          </TooltipTrigger>
          <TooltipContent>More information</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  );
}
