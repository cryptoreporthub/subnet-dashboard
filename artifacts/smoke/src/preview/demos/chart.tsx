import {
  Bar,
  BarChart,
  CartesianGrid,
  XAxis,
  YAxis,
} from 'recharts';
import type { ChartConfig } from '../../components/ui/chart';
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from '../../components/ui/chart';

const chartConfig: ChartConfig = {
  desktop: { label: 'Desktop', color: 'var(--color-chart-1)' },
  mobile: { label: 'Mobile', color: 'var(--color-chart-2)' },
};

const chartData = [
  { month: 'Jan', desktop: 186, mobile: 80 },
  { month: 'Feb', desktop: 305, mobile: 200 },
  { month: 'Mar', desktop: 237, mobile: 120 },
  { month: 'Apr', desktop: 273, mobile: 190 },
  { month: 'May', desktop: 209, mobile: 130 },
];

export function ChartDemo() {
  return (
    <div className="max-w-2xl rounded-xl border bg-card p-6">
      <div className="mb-4">
        <p className="font-medium">Monthly visitors</p>
        <p className="text-sm text-muted-foreground">Desktop and mobile traffic.</p>
      </div>
      <ChartContainer config={chartConfig} className="max-h-72 w-full">
        <BarChart data={chartData} accessibilityLayer>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="month" tickLine={false} axisLine={false} />
          <YAxis tickLine={false} axisLine={false} width={30} />
          <ChartTooltip content={<ChartTooltipContent />} />
          <ChartLegend content={<ChartLegendContent />} />
          <Bar dataKey="desktop" fill="var(--color-desktop)" radius={4} />
          <Bar dataKey="mobile" fill="var(--color-mobile)" radius={4} />
        </BarChart>
      </ChartContainer>
    </div>
  );
}
