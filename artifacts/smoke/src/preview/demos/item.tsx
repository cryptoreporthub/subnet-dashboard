import { FileText, MoreHorizontal } from 'lucide-react';
import { Button } from '../../components/ui/button';
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemFooter,
  ItemGroup,
  ItemHeader,
  ItemMedia,
  ItemSeparator,
  ItemTitle,
} from '../../components/ui/item';

export function ItemDemo() {
  return (
    <ItemGroup className="max-w-xl rounded-xl border bg-card p-2">
      <Item variant="muted">
        <ItemHeader>
          <span className="text-xs text-muted-foreground">Updated today</span>
          <span className="text-xs text-muted-foreground">Draft</span>
        </ItemHeader>
        <ItemMedia variant="icon">
          <FileText />
        </ItemMedia>
        <ItemContent>
          <ItemTitle>Product brief</ItemTitle>
          <ItemDescription>
            Goals, customer context, and launch requirements.
          </ItemDescription>
        </ItemContent>
        <ItemActions>
          <Button variant="ghost" size="icon" aria-label="More actions">
            <MoreHorizontal />
          </Button>
        </ItemActions>
        <ItemFooter>
          <span className="text-xs text-muted-foreground">4 collaborators</span>
        </ItemFooter>
      </Item>
      <ItemSeparator />
      <Item size="sm">
        <ItemContent>
          <ItemTitle>Launch checklist</ItemTitle>
          <ItemDescription>Eight of ten tasks complete.</ItemDescription>
        </ItemContent>
      </Item>
    </ItemGroup>
  );
}
