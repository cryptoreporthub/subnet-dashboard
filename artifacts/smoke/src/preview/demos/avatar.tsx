import { Avatar, AvatarFallback, AvatarImage } from '../../components/ui/avatar';
import { Row } from '../parts';

export function AvatarDemo() {
  return (
    <div className="rounded-xl border bg-card p-6">
      <Row label="Sizes and fallback">
        <Avatar className="h-8 w-8">
          <AvatarFallback>AL</AvatarFallback>
        </Avatar>
        <Avatar>
          <AvatarImage
            src={`${import.meta.env.BASE_URL}favicon.svg`}
            alt="Design system mark"
          />
          <AvatarFallback>SC</AvatarFallback>
        </Avatar>
        <Avatar className="h-14 w-14">
          <AvatarFallback>DT</AvatarFallback>
        </Avatar>
      </Row>
    </div>
  );
}
