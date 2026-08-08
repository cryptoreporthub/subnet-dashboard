import { useForm } from 'react-hook-form';
import { Button } from '../../components/ui/button';
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '../../components/ui/form';
import { Input } from '../../components/ui/input';

type ProfileForm = {
  username: string;
};

export function FormDemo() {
  const form = useForm<ProfileForm>({
    defaultValues: { username: '' },
  });

  return (
    <div className="max-w-md rounded-xl border bg-card p-6">
      <Form {...form}>
        <form
          className="space-y-4"
          onSubmit={form.handleSubmit(() => undefined)}
        >
          <FormField
            control={form.control}
            name="username"
            rules={{ required: 'Enter a username.' }}
            render={({ field }) => (
              <FormItem>
                <FormLabel>Username</FormLabel>
                <FormControl>
                  <Input placeholder="alex" {...field} />
                </FormControl>
                <FormDescription>Your public display name.</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <Button type="submit">Save profile</Button>
        </form>
      </Form>
    </div>
  );
}
