import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '../../components/ui/tabs';

export function TabsDemo() {
  return (
    <div className="max-w-lg rounded-xl border bg-card p-6">
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="activity">Activity</TabsTrigger>
          <TabsTrigger value="settings" disabled>
            Settings
          </TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="rounded-md border p-4 text-sm">
          Project summary and recent milestones.
        </TabsContent>
        <TabsContent value="activity" className="rounded-md border p-4 text-sm">
          Latest changes from your team.
        </TabsContent>
      </Tabs>
    </div>
  );
}
