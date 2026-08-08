import { useState } from 'react';
import {
  Menubar,
  MenubarCheckboxItem,
  MenubarContent,
  MenubarItem,
  MenubarMenu,
  MenubarRadioGroup,
  MenubarRadioItem,
  MenubarSeparator,
  MenubarShortcut,
  MenubarSub,
  MenubarSubContent,
  MenubarSubTrigger,
  MenubarTrigger,
} from '../../components/ui/menubar';

export function MenubarDemo() {
  const [showToolbar, setShowToolbar] = useState(true);
  const [zoom, setZoom] = useState('100');

  return (
    <div className="max-w-lg rounded-xl border bg-card p-6">
      <Menubar>
        <MenubarMenu>
          <MenubarTrigger>File</MenubarTrigger>
          <MenubarContent>
            <MenubarItem>
              New tab <MenubarShortcut>Cmd T</MenubarShortcut>
            </MenubarItem>
            <MenubarItem>New window</MenubarItem>
            <MenubarSeparator />
            <MenubarItem disabled>Print</MenubarItem>
          </MenubarContent>
        </MenubarMenu>
        <MenubarMenu>
          <MenubarTrigger>View</MenubarTrigger>
          <MenubarContent>
            <MenubarCheckboxItem
              checked={showToolbar}
              onCheckedChange={(checked) => setShowToolbar(checked === true)}
            >
              Show toolbar
            </MenubarCheckboxItem>
            <MenubarSub>
              <MenubarSubTrigger>Zoom</MenubarSubTrigger>
              <MenubarSubContent>
                <MenubarRadioGroup value={zoom} onValueChange={setZoom}>
                  <MenubarRadioItem value="90">90%</MenubarRadioItem>
                  <MenubarRadioItem value="100">100%</MenubarRadioItem>
                  <MenubarRadioItem value="110">110%</MenubarRadioItem>
                </MenubarRadioGroup>
              </MenubarSubContent>
            </MenubarSub>
          </MenubarContent>
        </MenubarMenu>
      </Menubar>
    </div>
  );
}
