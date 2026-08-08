import { FileText, Home, Settings } from 'lucide-react';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInput,
  SidebarInset,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarSeparator,
} from '../../components/ui/sidebar';

export function SidebarDemo() {
  return (
    <div className="h-80 max-w-3xl overflow-hidden rounded-xl border">
      <SidebarProvider className="h-full min-h-0">
        <Sidebar collapsible="none">
          <SidebarHeader>
            <p className="px-2 text-sm font-semibold">Acme workspace</p>
            <SidebarInput placeholder="Search" />
          </SidebarHeader>
          <SidebarSeparator />
          <SidebarContent>
            <SidebarGroup>
              <SidebarGroupLabel>Workspace</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  <SidebarMenuItem>
                    <SidebarMenuButton isActive>
                      <Home /> <span>Home</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                  <SidebarMenuItem>
                    <SidebarMenuButton>
                      <FileText /> <span>Documents</span>
                    </SidebarMenuButton>
                    <SidebarMenuBadge>12</SidebarMenuBadge>
                  </SidebarMenuItem>
                  <SidebarMenuItem>
                    <SidebarMenuButton>
                      <Settings /> <span>Settings</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          </SidebarContent>
          <SidebarFooter>
            <p className="px-2 text-xs text-muted-foreground">3 members online</p>
          </SidebarFooter>
        </Sidebar>
        <SidebarInset className="min-h-0 p-6">
          <p className="font-medium">Project canvas</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Main content remains contained beside the navigation.
          </p>
        </SidebarInset>
      </SidebarProvider>
    </div>
  );
}
