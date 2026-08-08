import {
  NavigationMenu,
  NavigationMenuContent,
  NavigationMenuIndicator,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
  NavigationMenuTrigger,
  navigationMenuTriggerStyle,
} from '../../components/ui/navigation-menu';

export function NavigationMenuDemo() {
  return (
    <div className="min-h-48 max-w-2xl rounded-xl border bg-card p-6">
      <NavigationMenu>
        <NavigationMenuList>
          <NavigationMenuItem>
            <NavigationMenuTrigger>Products</NavigationMenuTrigger>
            <NavigationMenuContent>
              <ul className="grid w-80 gap-2 p-4">
                <li>
                  <NavigationMenuLink
                    href="#page=navigation-menu"
                    className="block rounded-md p-3 hover:bg-accent"
                  >
                    <span className="font-medium">Apps</span>
                    <span className="block text-sm text-muted-foreground">
                      Build and publish full-stack projects.
                    </span>
                  </NavigationMenuLink>
                </li>
                <li>
                  <NavigationMenuLink
                    href="#page=navigation-menu"
                    className="block rounded-md p-3 hover:bg-accent"
                  >
                    <span className="font-medium">Teams</span>
                    <span className="block text-sm text-muted-foreground">
                      Collaborate with shared tools and access.
                    </span>
                  </NavigationMenuLink>
                </li>
              </ul>
            </NavigationMenuContent>
          </NavigationMenuItem>
          <NavigationMenuItem>
            <NavigationMenuLink
              href="#page=navigation-menu"
              className={navigationMenuTriggerStyle()}
            >
              Pricing
            </NavigationMenuLink>
          </NavigationMenuItem>
          <NavigationMenuIndicator />
        </NavigationMenuList>
      </NavigationMenu>
    </div>
  );
}
